#!/usr/bin/env python3
"""Stage the tested series on five files before touching a user-selected tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DISPLAY = Path('drivers/gpu/drm/i915/display')
FILES = ('intel_psr.c', 'intel_vrr.c', 'intel_display_params.c',
         'intel_display_params.h', 'intel_display_debugfs.c')


def select_profile(source, profiles):
    for profile in profiles:
        if all(hashlib.sha256((source / item['file']).read_bytes()).hexdigest()
               == item['original_sha256'] for item in profile['files']):
            return profile
    return None


def main():
    parser = argparse.ArgumentParser(description='先在临时副本验证完整补丁组合，再应用到指定Linux源码树。')
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true', help='仅验证，不修改源码树')
    args = parser.parse_args()
    source = args.source.resolve()
    profiles = json.loads((ROOT / 'patches/source-files.json').read_text())['bases']
    for name in FILES:
        if not (source / DISPLAY / name).is_file():
            parser.error(f'缺少完整内核源码文件：{DISPLAY / name}')
    profile = select_profile(source, profiles)
    if profile is None:
        parser.error('原文件未整体匹配已登记版本，或已打补丁；源码树未修改。')
    fingerprints = profile['files']
    print('识别源码：' + profile['id'])
    with tempfile.TemporaryDirectory(prefix='psr2-patches-') as temp:
        stage = Path(temp)
        (stage / DISPLAY).mkdir(parents=True)
        for name in FILES:
            shutil.copy2(source / DISPLAY / name, stage / DISPLAY / name)
        for name in (ROOT / 'patches/series').read_text().splitlines():
            if not name or name.startswith('#'):
                continue
            patch = ROOT / 'patches' / name
            with patch.open('rb') as stream:
                result = subprocess.run(['patch', '--batch', '--forward', '--fuzz=2',
                                         '-p1', '-d', str(stage)], stdin=stream,
                                        capture_output=True, text=True)
            if result.returncode:
                raise SystemExit(f'{name}不能完整应用；原源码树未修改。可能已打补丁或版本不符。\n'
                                 + result.stdout + result.stderr)
        for item in fingerprints:
            digest = hashlib.sha256((stage / item['file']).read_bytes()).hexdigest()
            if digest != item['patched_sha256']:
                raise SystemExit(f"补丁结果与实机版本不符，原树未修改：{item['file']}")
        if args.check:
            print('五个补丁验证通过；源码树未修改。')
            return
        for name in FILES:
            shutil.copy2(stage / DISPLAY / name, source / DISPLAY / name)
        print('补丁已应用到指定树的5个文件；未构建、安装或修改启动参数。')


if __name__ == '__main__':
    main()
