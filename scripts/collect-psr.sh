#!/usr/bin/env bash
# Guided, read-only PSR snapshots. Run as the normal user, not with sudo.
set -euo pipefail

if [[ ! -t 0 ]]; then
    echo '请在交互终端中运行：bash scripts/collect-psr.sh' >&2
    exit 1
fi
if (( EUID == 0 )); then
    echo '请用普通用户运行；脚本只在读取 debugfs/dmesg 时使用 sudo。' >&2
    exit 1
fi

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p -- "$project_dir/results"
sudo -v
status_path=$(sudo bash -c '
    shopt -s nullglob
    declare -A seen=()
    paths=()
    for path in /sys/kernel/debug/dri/*/i915_edp_psr_status; do
        resolved=$(readlink -f -- "$path")
        if [[ ! ${seen[$resolved]+present} ]]; then
            paths+=("$resolved")
            seen[$resolved]=1
        fi
    done
    if (( ${#paths[@]} != 1 )); then
        printf "找到 %s 个 PSR 状态文件；需要恰好一个。\n" "${#paths[@]}" >&2
        exit 1
    fi
    printf "%s\n" "${paths[0]}"
')
sudo cat -- "$status_path" >/dev/null
run_dir=$(mktemp -d "$project_dir/results/simple-psr-$(date +%Y%m%d-%H%M%S)-XXXXXX")

{
    date --iso-8601=seconds
    uname -a
    printf '\ncmdline: '
    cat /proc/cmdline
    printf '\nstatus file: %s\n' "$status_path"
    for parameter in enable_psr psr2_su_area_max_lines psr2_su_y_alignment psr2_idle_frames vrr_ctl_bit26; do
        parameter_path="/sys/module/xe/parameters/$parameter"
        printf '%s = ' "$parameter"
        if sudo test -f "$parameter_path"; then
            sudo cat -- "$parameter_path"
        else
            printf '参数不存在\n'
        fi
    done
} >"$run_dir/environment.txt"

# Keep the same guided steps, but retain mode, effective native granularity,
# DSC and plane configuration for experiments that change the requested grid.
sudo cat -- "$status_path" >"$run_dir/initial-status.txt"
debug_dir=${status_path%/*}
if ! sudo cat -- "$debug_dir/i915_display_info" >"$run_dir/display-info.txt" 2>"$run_dir/display-info.error.txt"; then
    echo '显示配置读取失败，错误已保留；PSR快照仍可采集。' >&2
fi
if ! grep -q '^PSR mode: PSR2 enabled' "$run_dir/initial-status.txt"; then
    echo "当前未显示PSR2 enabled，不继续PSR2两步实验。配置已保存：$run_dir" >&2
    exit 1
fi

snapshot() {
    local target=$1
    {
        date --iso-8601=ns
        sudo cat -- "$status_path"
        printf '\n'
    } >>"$target"
}

echo '只做两步：静止画面、底部鼠标。无需知道坐标或行数。'
echo '请保持本轮启动参数；不要在测试前登出重登。'
echo '第 1 步：按 Enter 后有 5 秒切到静止桌面（不留闪烁输入光标）。'
echo '然后不动鼠标、不打字，约 30 秒后回终端继续。'
read -r -p '准备好后按 Enter：' _
sleep 5
sleep 20
for sample in 1 2 3; do
    snapshot "$run_dir/idle.log"
    if (( sample < 3 )); then sleep 2; fi
done

echo '第 2 步：按 Enter 后有 5 秒切回桌面。'
echo '将鼠标推到屏幕最底边，沿底边左右移动约 10 秒，然后回终端。'
read -r -p '准备好后按 Enter：' _
sleep 5
for sample in 1 2 3 4 5 6 7 8 9 10; do
    snapshot "$run_dir/bottom.log"
    if (( sample < 10 )); then sleep 1; fi
done
read -r -p '底部移动是否花屏？输入 是 / 否 / 不确定：' observation
printf '底部鼠标花屏：%s\n' "$observation" >"$run_dir/observation.txt"
read -r -p '本轮刷新率和缩放（可直接 Enter 跳过）：' display_note
printf '刷新率和缩放：%s\n' "$display_note" >>"$run_dir/observation.txt"
if ! sudo dmesg >"$run_dir/dmesg.log" 2>"$run_dir/dmesg-error.txt"; then
    echo 'dmesg 未能读取，错误已保存；其余采集仍有效。' >&2
fi
echo "采集完成：$run_dir"
echo '下面只汇总静止阶段的状态，是否真正自刷新需结合原始日志判断：'
awk '/PSR mode:|Source PSR\/PanelReplay (ctl|status):|MAN_TRK_CTL/' "$run_dir/idle.log"
echo '这是寄存器快照采集，尚不包含每次提交的 SU/光标坐标轨迹，也不是功耗测量。'
