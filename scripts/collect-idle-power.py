#!/usr/bin/env python3
"""One battery idle baseline; no settings, registers or parameters are written."""
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
from datetime import datetime

PROJECT = Path(__file__).resolve().parent.parent
SUPPLIES = Path('/sys/class/power_supply')
BACKLIGHT = Path('/sys/class/backlight')
INTERVAL = 5
SECONDS = 180


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def number(path):
    try:
        return int(read(path))
    except (TypeError, ValueError):
        return None


def sample(battery):
    return {
        'time': datetime.now().astimezone().isoformat(),
        'monotonic': time.monotonic(),
        'boottime': time.clock_gettime(time.CLOCK_BOOTTIME),
        'status': read(battery / 'status'),
        'power_uw': number(battery / 'power_now'),
        'energy_uwh': number(battery / 'energy_now'),
        'capacity_percent': number(battery / 'capacity'),
        'external_online': {p.name: number(p / 'online') for p in SUPPLIES.iterdir()
                            if read(p / 'type') != 'Battery' and (p / 'online').exists()},
        'brightness': {p.name: {k: number(p / k) for k in
                               ('brightness', 'actual_brightness', 'max_brightness')}
                       for p in BACKLIGHT.iterdir()},
        'loadavg': read('/proc/loadavg'),
    }


def summarize(rows, complete):
    reasons = []
    if not complete or len(rows) < 2:
        reasons.append('采集未完成')
    if any(r['status'] != 'Discharging' or not isinstance(r['power_uw'], int)
           or r['power_uw'] <= 0 or any(v == 1 for v in r['external_online'].values())
           for r in rows):
        reasons.append('存在非电池放电、接入外电或无有效功率的样本')
    if rows and any(r['brightness'] != rows[0]['brightness'] for r in rows):
        reasons.append('屏幕亮度或背光状态发生变化')
    if rows and any(abs((r['boottime'] - rows[0]['boottime']) -
                       (r['monotonic'] - rows[0]['monotonic'])) > 1 for r in rows):
        reasons.append('测量期间发生挂起')
    gaps = [b['monotonic'] - a['monotonic'] for a, b in zip(rows, rows[1:])]
    if any(g <= 0 or g > INTERVAL * 2.5 for g in gaps):
        reasons.append('采样间隔异常')
    elapsed = rows[-1]['monotonic'] - rows[0]['monotonic'] if len(rows) > 1 else 0
    result = {'complete': complete, 'samples': len(rows), 'elapsed_seconds': elapsed,
              'valid_idle_baseline': False, 'invalid_reasons': reasons,
              'scope': '整机电池功率，非PSR单项；不是驻留比例或Windows等效性测量'}
    if reasons or elapsed <= 0:
        return result
    watts = [r['power_uw'] / 1e6 for r in rows]
    result.update(valid_idle_baseline=True,
                  time_weighted_mean_w=sum((a + b) / 2 * dt for a, b, dt in
                                           zip(watts, watts[1:], gaps)) / elapsed,
                  median_w=statistics.median(watts), min_w=min(watts), max_w=max(watts),
                  distinct_power_readings=len(set(watts)))
    first, last = rows[0]['energy_uwh'], rows[-1]['energy_uwh']
    if first is not None and last is not None:
        result['energy_drop_uwh'] = first - last
        result['energy_based_mean_w'] = (first - last) / 1e6 * 3600 / elapsed
    return result


def psr_snapshot(target):
    # Only existing, read-only PSR debugfs entries. Resolve duplicate DRM aliases.
    command = r'''
set -euo pipefail
shopt -s nullglob
declare -A seen=()
for name in enable_psr psr2_su_area_max_lines psr2_su_y_alignment; do
    printf '%s = ' "$name"
    cat -- "/sys/module/xe/parameters/$name"
done
for path in /sys/kernel/debug/dri/*/i915_edp_psr_status; do
    resolved=$(readlink -f -- "$path")
    if [[ ! ${seen[$resolved]+present} ]]; then
        seen[$resolved]=1
        printf 'source: %s\n' "$resolved"
        cat -- "$resolved"
    fi
done
if (( ${#seen[@]} != 1 )); then exit 1; fi
'''
    try:
        result = subprocess.run(['sudo', '-n', 'bash', '-c', command],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        target.with_suffix('.error.txt').write_text(str(error) + '\n')
        return False
    target.write_text(result.stdout)
    target.with_suffix('.error.txt').write_text(result.stderr)
    return result.returncode == 0


def main():
    if os.geteuid() == 0 or not os.isatty(0):
        raise SystemExit('请在交互终端以普通用户运行：python3 scripts/collect-idle-power.py')
    batteries = [p for p in SUPPLIES.iterdir() if read(p / 'type') == 'Battery'
                 and read(p / 'present') == '1']
    if len(batteries) != 1:
        raise SystemExit('需要恰好一块可读电池；未开始采集。')
    battery = batteries[0]
    initial = sample(battery)
    if (initial['status'] != 'Discharging' or initial['power_uw'] is None
            or initial['power_uw'] <= 0
            or any(v == 1 for v in initial['external_online'].values())):
        raise SystemExit('请拔掉电源，确认使用电池后再运行；未开始采集。')
    print('保持当前104参数与120Hz/200%，固定亮度，使用静止桌面，暂停动态壁纸/视频。')
    print('按Enter后45秒准备，随后测量3分钟；期间保持屏幕亮着、不操作。')
    print('只在测量前后读取PSR状态，测量期间不轮询GPU寄存器。')
    subprocess.run(['sudo', '-v'], check=True)
    (PROJECT / 'results').mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='idle-power-' + datetime.now().strftime('%Y%m%d-%H%M%S-'),
                                dir=PROJECT / 'results'))
    metadata = {'time': datetime.now().astimezone().isoformat(), 'kernel': os.uname().release,
                'cmdline': read('/proc/cmdline'), 'battery': str(battery),
                'boot_id': read('/proc/sys/kernel/random/boot_id'),
                'uptime': read('/proc/uptime'),
                'platform_profile': read('/sys/firmware/acpi/platform_profile'),
                'governor': read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor'),
                'units': {'power_now': 'uW', 'energy_now': 'uWh'},
                'interval_seconds': INTERVAL, 'duration_seconds': SECONDS,
                'warmup_seconds': 45, 'initial': initial}
    (run / 'environment.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    psr_snapshot(run / 'psr-before.txt')
    input('准备好后按Enter，然后切到静止桌面，约4分钟后返回：')
    rows, complete = [], False
    try:
        time.sleep(45)
        start = time.monotonic()
        with (run / 'samples.jsonl').open('w') as stream:
            for index in range(SECONDS // INTERVAL + 1):
                time.sleep(max(0, start + index * INTERVAL - time.monotonic()))
                row = sample(battery)
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                stream.flush()
        complete = True
    except KeyboardInterrupt:
        pass
    result = summarize(rows, complete)
    result['psr_after_read_ok'] = psr_snapshot(run / 'psr-after.txt')
    print('采集结束。')
    result['user_note'] = input('期间是否熄屏、自动换壁纸或被打扰？正常直接Enter，否则说明：')
    if result['user_note'].strip():
        result['valid_idle_baseline'] = False
        result['invalid_reasons'].append('用户记录了干扰，需复核')
    (run / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('配置已保存：' + str(run))
    if result['valid_idle_baseline']:
        print(f"初步整机平均功率：{result['time_weighted_mean_w']:.2f} W；需结合PSR状态与条件判断。")
    else:
        print('此轮不直接作为稳定空闲基线；原始数据已保留。')


if __name__ == '__main__':
    main()
