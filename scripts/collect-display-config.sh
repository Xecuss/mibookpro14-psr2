#!/usr/bin/env bash
# One-shot reads through the existing Linux DRM debugfs interfaces.
# No parameter/register writes, modesets, polling or interaction sequence.
set -euo pipefail
if (( EUID == 0 )); then
    echo '请用普通用户运行；脚本会通过 sudo 读取 debugfs。' >&2
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
        printf "找到 %s 个 PSR 状态文件，需要恰好一个。\n" "${#paths[@]}" >&2
        exit 1
    fi
    printf "%s\n" "${paths[0]}"
')
debug_dir=${status_path%/*}
run_dir=$(mktemp -d "$project_dir/results/display-config-$(date +%Y%m%d-%H%M%S)-XXXXXX")
{
    date --iso-8601=seconds
    uname -a
    printf '\ncmdline: '
    cat /proc/cmdline
    printf '\ndebugfs: %s\n' "$debug_dir"
    for parameter in enable_psr psr2_su_area_max_lines psr2_su_y_alignment psr2_idle_frames vrr_ctl_bit26; do
        printf '%s = ' "$parameter"
        path="/sys/module/xe/parameters/$parameter"
        if sudo test -f "$path"; then sudo cat -- "$path"; else echo '参数不存在'; fi
    done
} >"$run_dir/environment.txt"

# Read the security state; never change it. Writable debugfs entries can be
# rejected by lockdown even when opened read-only by root.
lockdown_state=unknown
if [[ -r /sys/kernel/security/lockdown ]]; then
    lockdown_state=$(cat /sys/kernel/security/lockdown)
fi
printf '%s\n' "$lockdown_state" >"$run_dir/lockdown.txt"

read_file() {
    local source=$1 target=$2
    if sudo test -f "$source"; then
        if ! sudo cat -- "$source" >"$run_dir/$target" 2>"$run_dir/$target.error.txt"; then
            echo "读取失败，错误保留：$target" >&2
        fi
    else
        printf '文件不存在：%s\n' "$source" >"$run_dir/$target.error.txt"
    fi
}
read_file "$status_path" psr-status.txt
read_file "$debug_dir/i915_display_info" display-info.txt
# This optional connector interface is registered as 0644 and has a write
# handler. Under lockdown, use the read-only display dump instead.
mapfile -t dsc_files < <(sudo bash -c '
    shopt -s nullglob
    for path in "$1"/*/i915_dsc_fec_support; do printf "%s\n" "$path"; done
' _ "$debug_dir")
if (( ${#dsc_files[@]} == 0 )); then
    echo '没有发现连接器 DSC 状态接口；不将缺失解释为 DSC 关闭。' >"$run_dir/dsc-status.error.txt"
fi
for path in "${dsc_files[@]}"; do
    connector_dir=${path%/*}
    connector=${connector_dir##*/}
    if [[ "$lockdown_state" == *'[integrity]'* || "$lockdown_state" == *'[confidentiality]'* ]]; then
        printf '已跳过：内核 lockdown=%s；DSC 接口以 0644 注册，只读打开也受限制。使用 display-info.txt 判断当前配置。\n' \
            "$lockdown_state" >"$run_dir/dsc-$connector.txt.error.txt"
        continue
    fi
    if [[ -s "$run_dir/display-info.txt" ]] &&
       ! awk -v connector="$connector" '
           $0 ~ "\\[CONNECTOR:[0-9]+:" connector "\\]: status: connected$" { found=1 }
           END { exit !found }
       ' "$run_dir/display-info.txt"; then
        printf '已跳过：%s 没有已连接的显示输出；详见 display-info.txt。\n' "$connector" \
            >"$run_dir/dsc-$connector.txt.error.txt"
        continue
    fi
    read_file "$path" "dsc-$connector.txt"
done

echo "配置已保存：$run_dir"
echo '无需移动鼠标、修改参数或重启。请带回这个目录。'
if [[ "$lockdown_state" == *'[integrity]'* || "$lockdown_state" == *'[confidentiality]'* ]]; then
    echo '内核 lockdown 已启用，已跳过受限 DSC 接口；显示配置读取结果仍保留。'
fi
if [[ -s "$run_dir/psr-status.txt" ]]; then
    awk '/^PSR mode:/' "$run_dir/psr-status.txt"
    if grep -q '^PSR mode: PSR1 enabled' "$run_dir/psr-status.txt"; then
        echo '当前为 PSR1：此目录记录当前配置，不用于证明此前 PSR2 的配置。'
    fi
fi
if [[ -f "$run_dir/display-info.txt" ]]; then
    awk '/port_clock=|lane_count=|dsc-cfg: version:|compressed-bpp=|pipe src=|PSR SU:/' "$run_dir/display-info.txt"
fi
for path in "$run_dir"/dsc-*.txt; do
    if [[ -f "$path" ]]; then
        awk '/DSC_Enabled:|DSC_Sink_Support:/' "$path"
    fi
done
