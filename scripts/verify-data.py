#!/usr/bin/env python3
"""Recompute all public numeric samples without reading local hardware."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    total = 0
    files = sorted((ROOT / 'data/power').glob('*.json'))
    require(len(files) == 6, 'Expected six power runs')
    for path in files:
        data = json.loads(path.read_text())
        rows, expected = data['samples'], data['expected']
        require(len(rows) == expected['samples'], str(path))
        t = [r['elapsed_s'] for r in rows]
        w = [r['power_w'] for r in rows]
        require(t[0] == 0 and t[-1] > 0, 'Relative monotonic time required')
        require(all(math.isfinite(v) for r in rows for v in
                    (r['elapsed_s'], r['power_w'], r['energy_wh'])), 'Nonfinite sample')
        gaps = [b - a for a, b in zip(t, t[1:])]
        require(all(0 < gap < 12.5 for gap in gaps), 'Abnormal sampling gap')
        require(all(r['discharging'] and not r['external_online'] and r['power_w'] > 0
                    and r['brightness'] == rows[0]['brightness'] for r in rows),
                'Power/brightness conditions differ')
        mean = sum((a + b) / 2 * dt for a, b, dt in zip(w, w[1:], gaps)) / t[-1]
        drop = rows[0]['energy_wh'] - rows[-1]['energy_wh']
        energy_mean = drop * 3600 / t[-1]
        for actual, key in [(mean, 'time_weighted_mean_w'), (drop, 'energy_drop_wh'),
                            (energy_mean, 'energy_based_mean_w'), (t[-1], 'duration_s')]:
            require(math.isclose(actual, expected[key], abs_tol=1e-9), data['id'] + ': ' + key)
        total += len(rows)
        print(f"{data['id']:14} {len(rows):2} samples, mean {mean:.6f} W, energy {energy_mean:.6f} W")
    require(total == 258, 'Expected 258 power samples')

    registers = 0
    for path in sorted((ROOT / 'data/registers').glob('*.json')):
        data = json.loads(path.read_text())
        for s in data['snapshots']:
            registers += 1
            regs = {k: int(v, 16) for k, v in s['registers'].items()}
            man = regs['MAN_TRK_CTL']
            require(s['y1'] == ((man >> 16) & 0x1fff) and
                    s['y2_exclusive'] == (man & 0x1fff) + 1, 'MAN decode mismatch')
            require(s['partial'] == bool(man & (1 << 31)) and
                    s['cff'] == bool(man & (1 << 13)) and
                    s['single_full'] == bool(man & (1 << 14)), 'MAN flags mismatch')
            if s['partial'] and not s['cff'] and not s['single_full']:
                y1, y2 = s['y1'], s['y2_exclusive']
                require(0 <= y1 < y2 <= 2080, 'Partial out of bounds')
                for plane in (1, 2, 3, 5, 6):
                    prefix = f'SEL_FETCH_PLANE{plane}_'
                    if not regs.get(prefix + 'CTL', 0) & (1 << 31):
                        continue
                    pos, size = regs[prefix + 'POS'], regs[prefix + 'SIZE']
                    require(pos >> 16 == y1 and (size >> 16) + 1 == y2 - y1
                            and (size & 0xffff) + 1 == 3120
                            and regs[prefix + 'OFFSET'] == pos, 'Pipe/plane mismatch')
                if 'grid-' in path.stem:
                    grid = int(path.stem.rsplit('-', 1)[1])
                    require(y1 % grid == y2 % grid == 0, 'Grid mismatch')
    provenance = json.loads((ROOT / 'patches/provenance.json').read_text())
    for entry in provenance:
        patch = (ROOT / 'patches' / entry['file']).read_text()
        diff = patch[patch.index('diff --git '):].encode()
        require(hashlib.sha256(diff).hexdigest() == entry['diff_sha256'], 'Patch diff changed')
    profiles = json.loads((ROOT / 'patches/source-files.json').read_text())['bases']
    require({p['id'] for p in profiles} == {'linux-7.2.9', 'linux-7.2.10'}, 'Source profiles changed')
    for profile in profiles:
        require(len(profile['files']) == 5, 'Expected five source files per profile')
        require(len({f['file'] for f in profile['files']}) == 5, 'Duplicate source fingerprint')
        for item in profile['files']:
            for key in ('original_sha256', 'patched_sha256'):
                require(len(item[key]) == 64 and all(c in '0123456789abcdef' for c in item[key]),
                        'Invalid source fingerprint')
    print(f'PASS: {total} power points, {registers} register snapshots, five tested patch bodies.')


if __name__ == '__main__':
    main()
