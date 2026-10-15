#!/usr/bin/env python3
"""Four-minute battery video workload, with an explicitly auditioned audio cue."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from datetime import datetime

# Reuse the already exercised sysfs sampling, unit conversion and PSR reader.
SOURCE = Path(__file__).with_name('collect-idle-power.py')
SPEC = importlib.util.spec_from_file_location('idle_power', SOURCE)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
DURATION = 240
INTERVAL = 5
PREPARE = 45


def stamp():
    return {'time': datetime.now().astimezone().isoformat(),
            'monotonic': time.monotonic()}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def make_tone(path, count=1):
    """Quiet, faded PCM tones; no dependency on terminal bell configuration."""
    rate, length, gap = 48000, 0.25, 0.18
    pcm = bytearray()
    for tone in range(count):
        if tone:
            pcm.extend(b'\0\0' * int(rate * gap))
        for i in range(int(rate * length)):
            fade = min(1.0, i / (rate * 0.01), (rate * length - 1 - i) / (rate * 0.01))
            value = int(0.22 * 32767 * fade * math.sin(2 * math.pi * 880 * i / rate))
            pcm.extend(struct.pack('<h', value))
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm)


def audition(tone):
    for name in ('pw-play', 'paplay', 'aplay'):
        executable = shutil.which(name)
        if not executable:
            continue
        print(f'使用 {name} 播放试听短音……', flush=True)
        try:
            result = subprocess.run([executable, str(tone)], capture_output=True,
                                    text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f'播放失败：{error}')
            continue
        if result.returncode != 0:
            print('播放失败：' + result.stderr.strip()[:400])
            continue
        if input('是否听到短音？输入 y 确认，其余输入尝试下一个播放器：').strip().lower() in ('y', 'yes', '是'):
            return executable
    raise RuntimeError('未确认听到声音，未开始测量。检查音量、静音和输出设备后重试。')


def launch_cue(player, tone, error_stream):
    event = stamp()
    process = subprocess.Popen([player, str(tone)], stdout=subprocess.DEVNULL,
                               stderr=error_stream)
    event['process_launched'] = stamp()
    event['meaning'] = '音频进程启动请求；不是扬声器实际出声或视频播放时间'
    return process, event


def finish_cue(process):
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return 'timeout'


def collect_window(battery, run, player, tone):
    """Fixed monotonic deadlines, with the cue launch anchored to time zero."""
    rows, complete, events, failure = [], False, {}, None
    process = None
    try:
        with (run / 'audio-start.error.txt').open('w') as errors, (run / 'samples.jsonl').open('w') as stream:
            process, events['start_cue'] = launch_cue(player, tone, errors)
            start = events['start_cue']['monotonic']
            for index in range(DURATION // INTERVAL + 1):
                time.sleep(max(0, start + index * INTERVAL - time.monotonic()))
                if process.poll() not in (None, 0):
                    raise RuntimeError('开始短音播放进程失败；本轮不能用于同步比较。')
                row = BASE.sample(battery)
                row['seconds_from_cue_request'] = row['monotonic'] - start
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                stream.flush()
            complete = True
    except (KeyboardInterrupt, OSError, RuntimeError) as error:
        failure = type(error).__name__ + ': ' + str(error)
    finally:
        if process is not None:
            events['start_cue_exit_code'] = finish_cue(process)
        events['sampling_finished'] = stamp()
        save(run / 'timing.json', events)
    result = BASE.summarize(rows, complete)
    result['valid_power_window'] = result.pop('valid_idle_baseline')
    result['scope'] = '视频播放时的整机电池功率，包含显示、解码、音频、网络等；非空闲基线或PSR单项功率'
    result['requested_duration_seconds'] = DURATION
    result['failure'] = failure
    if failure or events.get('start_cue_exit_code') != 0:
        result['valid_power_window'] = False
        result['invalid_reasons'].append('采集或开始声音失败，见failure、timing.json及audio-start.error.txt')
    if rows:
        result['first_sample_seconds_from_cue_request'] = rows[0]['seconds_from_cue_request']
        result['last_sample_seconds_from_cue_request'] = rows[-1]['seconds_from_cue_request']
    save(run / 'summary.json', result)
    return result


def display_snapshot(run):
    sources = [line.removeprefix('source: ') for line in
               (run / 'psr-before.txt').read_text().splitlines() if line.startswith('source: ')]
    if len(sources) != 1:
        return False
    path = Path(sources[0]).with_name('i915_display_info')
    try:
        result = subprocess.run(['sudo', '-n', 'cat', '--', str(path)],
                                capture_output=True, text=True, timeout=15)
        (run / 'display-info.txt').write_text(result.stdout)
        (run / 'display-info.error.txt').write_text(result.stderr)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as error:
        (run / 'display-info.error.txt').write_text(str(error) + '\n')
        return False


def after_psr_snapshot(run):
    """Refresh expired sudo only after power sampling, retaining the first error."""
    result = {'psr_after_attempts': []}

    def attempt(name):
        item = {'file': name, 'started': stamp()}
        item['read_ok'] = BASE.psr_snapshot(run / name)
        item['finished'] = stamp()
        result['psr_after_attempts'].append(item)
        return item['read_ok']

    result['psr_after_read_ok'] = attempt('psr-after.txt')
    error = BASE.read(run / 'psr-after.error.txt') or ''
    if (not result['psr_after_read_ok'] and 'sudo:' in error
            and ('password' in error.lower() or '密码' in error)):
        print('功耗已保存。sudo认证已过期，请完成认证后补读结束状态；无需重测。', flush=True)
        try:
            auth = subprocess.run(['sudo', '-v'], check=False)
            result['psr_after_auth_exit_code'] = auth.returncode
            if auth.returncode == 0:
                result['psr_after_read_ok'] = attempt('psr-after-auth-retry.txt')
        except (OSError, KeyboardInterrupt) as error:
            result['psr_after_auth_error'] = type(error).__name__ + ': ' + str(error)
    return result


def main():
    parser = argparse.ArgumentParser(description='试听开始短音，45秒准备后采集4分钟视频播放整机功耗。')
    parser.add_argument('--test-beep', action='store_true', help='只试听声音，不读取PSR、不采集功耗')
    args = parser.parse_args()
    if os.geteuid() == 0 or not os.isatty(0):
        raise SystemExit('请在交互终端以普通用户运行：python3 scripts/collect-video-power.py')
    with tempfile.TemporaryDirectory(prefix='video-power-audio-') as audio_dir:
        tone, end_tone = Path(audio_dir) / 'start.wav', Path(audio_dir) / 'end.wav'
        make_tone(tone)
        make_tone(end_tone, count=2)
        try:
            player = audition(tone)
        except RuntimeError as error:
            raise SystemExit(str(error)) from error
        if args.test_beep:
            print('声音试听完成；正式采集运行同一命令并去掉 --test-beep。')
            return
        batteries = [p for p in BASE.SUPPLIES.iterdir() if BASE.read(p / 'type') == 'Battery'
                     and BASE.read(p / 'present') == '1']
        if len(batteries) != 1:
            raise SystemExit('需要恰好一块可读电池；未开始采集。')
        battery = batteries[0]
        initial = BASE.sample(battery)
        if (initial['status'] != 'Discharging' or not isinstance(initial['power_uw'], int)
                or initial['power_uw'] <= 0 or any(v == 1 for v in initial['external_online'].values())):
            raise SystemExit('请拔掉电源并确认电池放电；未开始采集。')
        print('保留终端和视频浏览器/播放器，关闭其他应用；固定PSR参数、亮度、刷新率/缩放和电源模式。')
        print('用同一视频、同一起点、固定画质/播放速度/窗口大小/音量，先加载并暂停。')
        print('45秒准备内切回视频，让播放器取得键盘焦点，将鼠标放到屏幕最右下角并静止。')
        print('开始单声：按空格播放；结束双声：暂停后回终端。测量中不移动鼠标、不操作。')
        print('本脚本不修改音量、屏保、PSR或其他设置；请确保这段时间不会自动熄屏。')
        video_note = input('视频链接/编号、起始时间（可空）：').strip()
        playback_note = input('画质/帧率、窗口或全屏、音量等（可空）：').strip()
        subprocess.run(['sudo', '-v'], check=True)
        (BASE.PROJECT / 'results').mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix='video-power-' + datetime.now().strftime('%Y%m%d-%H%M%S-'),
                                    dir=BASE.PROJECT / 'results'))
        metadata = {**stamp(), 'kernel': os.uname().release,
                    'cmdline': BASE.read('/proc/cmdline'), 'battery': str(battery),
                    'boot_id': BASE.read('/proc/sys/kernel/random/boot_id'),
                    'uptime': BASE.read('/proc/uptime'),
                    'platform_profile': BASE.read('/sys/firmware/acpi/platform_profile'),
                    'governor': BASE.read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor'),
                    'units': {'power_now': 'uW', 'energy_now': 'uWh'},
                    'duration_seconds': DURATION, 'interval_seconds': INTERVAL,
                    'prepare_seconds': PREPARE, 'audio_player': player,
                    'cue_audition_confirmed': True, 'video_note': video_note,
                    'playback_note': playback_note, 'initial': initial,
                    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'sampling_source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    'sync_limit': '声音请求时间已记录；无法测出声卡延迟、按键反应时间或视频实际开始帧。'}
        metadata['psr_before_read_ok'] = BASE.psr_snapshot(run / 'psr-before.txt')
        metadata['display_info_read_ok'] = display_snapshot(run) if (run / 'psr-before.txt').exists() else False
        save(run / 'environment.json', metadata)
        if not metadata['psr_before_read_ok']:
            print('PSR读取失败，错误已保存；功耗仍可采集，但需另核对当前PSR配置。')
        print('结果目录：' + str(run))
        try:
            input('准备好后按Enter；45秒后单声开始，随后采集4分钟：')
            time.sleep(PREPARE)
        except KeyboardInterrupt:
            save(run / 'summary.json', {'complete': False, 'valid_power_window': False,
                                        'invalid_reasons': ['准备阶段取消，未开始测量']})
            print('\n已取消，记录保留：' + str(run))
            return
        result = collect_window(battery, run, player, tone)
        if result['complete']:
            with (run / 'audio-end.error.txt').open('w') as errors:
                try:
                    process, end_event = launch_cue(player, end_tone, errors)
                    result['end_cue_exit_code'] = finish_cue(process)
                    timing = json.loads((run / 'timing.json').read_text())
                    timing['end_cue'] = end_event
                    save(run / 'timing.json', timing)
                except OSError as error:
                    result['end_cue_error'] = str(error)
                save(run / 'summary.json', result)
        print('\n采集已结束；请暂停视频后回终端。', flush=True)
        # Snapshot is after the window; playback may already have been paused.
        result.update(after_psr_snapshot(run))
        save(run / 'summary.json', result)
        try:
            result['user_note'] = input('是否正常播放？卡顿/缓冲、未听见开始音、熄屏、花屏或其他干扰请注明；正常直接Enter：')
        except (KeyboardInterrupt, EOFError):
            result['user_note'] = '未完成结束备注，请复核播放情况'
        if result['user_note'].strip():
            result['valid_power_window'] = False
            result['invalid_reasons'].append('用户备注需要复核')
        save(run / 'summary.json', result)
        print('采集已保存：' + str(run))
        if result['valid_power_window']:
            print(f"整机视频功率均值：{result['time_weighted_mean_w']:.2f} W；不是PSR单项功率。")
        else:
            print('原始数据已保留；此轮需复核，见summary.json。')


if __name__ == '__main__':
    main()
