# Xiaomi Book Pro 14 (2026) Linux PSR2 Workaround

[简体中文](README.zh-CN.md)

Experimental Linux kernel patches for the Xiaomi Book Pro 14 (2026) with Intel Arc B390 graphics. The workaround expands and aligns Panel Self Refresh 2 (PSR2) selective update (SU) regions. On the test laptop it reduced display corruption during mouse movement, rapid typing, and updates at the bottom of the screen while preserving partial updates and self-refresh when idle.

The recommended setting for the tested configuration is:

```text
xe.psr2_su_y_alignment=104
```

The cause of the corruption remains unknown. The 104-line setting was inspired by an update observed at the bottom of the display under Windows. The Windows driver's alignment setting was never read directly. An 80-line alignment also passed the scenarios tested with it. The 104-line alignment is preferred because it was also verified after resume. The power measurements do not establish a preference between 80 and 104.

## Important information

This experimental workaround was tested on one laptop and is provided as is. Replacing a graphics kernel module or rebuilding the initramfs can cause a blank screen, a crash, a failure to start the graphical session, or data loss. Save your work, keep a bootable distribution kernel and a backup of the original module, and review the [build, installation, and rollback guide (Chinese)](docs/BUILD.md). See the [license](LICENSE) for warranty and liability terms.

## Tested configuration

| Item | Configuration |
| --- | --- |
| Laptop | Xiaomi Book Pro 14 (2026), EDO OLED, 3120 × 2080 |
| GPU | Intel Arc B390, PCI ID `8086:b080` rev 04, subsystem `1d72:2424` |
| Main test environment | Fedora 44, `7.2.9-200.fc44.x86_64`, GNOME 50.5, Wayland, `xe` |
| Kernel upgrade | `7.2.10-200.fc44.x86_64` booted with the patched module. PSR2, deep sleep, and agreement between SU and plane coordinates were verified. The tester reported no display corruption in daily use. |
| Display | 120 Hz, with 200% scaling in the main 104-line test. Linux used HBR2 × 4, 18 bpp with dithering, and DSC disabled. |
| Windows reference | Graphics driver `32.0.101.8359`, 3120 × 2080 at 120 Hz |

The repository provides patches for the shared i915 display code used by `xe`, along with diagnostic tools. Building requires a complete source and build tree for the target kernel. The repository distributes source patches only.

## Build and enable the workaround

1. Follow the [build, installation, and rollback guide (Chinese)](docs/BUILD.md) to apply the patches, build `xe`, and install it for the target kernel. Rebuild the module for every kernel update.
2. Once the patched module is installed, press **e** at the GRUB menu to edit the boot entry. Add `xe.psr2_su_y_alignment=104` or replace the existing alignment value. Remove `xe.enable_psr=1` if present, since it forces PSR1. Leave `xe.psr2_su_area_max_lines` unset and keep `xe.psr2_idle_frames=-1` and `xe.vrr_ctl_bit26=N` at their defaults.
3. Press **Ctrl+X** to boot with these settings once. Keep refresh rate and scaling fixed during verification.

After logging in, run:

```bash
bash scripts/collect-display-config.sh
```

Check that PSR2 is enabled and look for `native_y_granularity=4`, `requested_y_alignment=104`, and `DSC=no`. To verify that the hardware is using the alignment, inspect both the SU and plane update coordinates. See the [findings](docs/FINDINGS.md) and [retest procedure](docs/TESTING.md) (both in Chinese) for the observed ranges and collection steps.

## Results on Linux 7.2.9

| Alignment | Mouse movement, typing, and bottom-of-screen corruption | Suspend and resume | Partial updates and idle self-refresh |
| --- | --- | --- | --- |
| 104 lines | No corruption observed | No corruption reported. Configuration and deep sleep checked afterward. | Partial update in 10 of 10 bottom-edge trials. Deep sleep in 3 of 3 idle trials. |
| 80 lines | No corruption observed | Untested | Partial update in 10 of 10 bottom-edge trials. Deep sleep in 3 of 3 idle trials. |

The bottom-of-screen updates covered 104, 208, or 312 lines with the 104-line alignment and 80 or 160 lines with the 80-line alignment. Corruption was reported with 52 and 208 lines without matching logs. A 26-line request is expected to fall back to the native four-line granularity because it fails the alignment constraint.

The 7.2.10 upgrade retained the kernel's default of disabling VRR DC balance. The measurements below are from 7.2.9. See the [upgrade notes (Chinese)](docs/UPGRADING.md).

## Power measurements

These figures come from whole-system battery telemetry. The power readings are time-weighted and the second estimate uses the change in reported battery energy. Each condition was tested once.

| Scenario | Configuration | Mean power reading | Mean from energy change |
| --- | --- | ---: | ---: |
| Desktop idle, 3 min | Linux PSR1 | 4.058 W | 3.780 W |
| Desktop idle, 3 min | Linux PSR2 + 104 | 3.958 W | 3.780 W |
| Desktop idle, 3 min | Windows reference | 4.361 W | 5.040 W |
| Same video, 4 min | Linux PSR1 | 9.489 W | 8.490 W |
| Same video, 4 min | Linux PSR2 + 104 | 8.831 W | 8.250 W |
| Same video, 4 min | Linux PSR2 + 80 | 9.118 W | 8.265 W |

The idle samples showed no clear increase with 104. In the video runs, PSR2 used less energy than PSR1, and the two PSR2 settings gave nearly identical energy estimates. The Windows reference used different brightness or HDR conditions and had sparse telemetry, limiting comparisons across operating systems. See the [test conditions and limitations (Chinese)](docs/POWER.md).

To recompute the results from the 258 published samples:

```bash
python3 scripts/verify-data.py
```

## Further documentation

- [Findings (Chinese)](docs/FINDINGS.md) covers the Windows observation, SU region expansion, and the open questions about the panel.
- [Retest procedure (Chinese)](docs/TESTING.md) covers display-state capture and video power measurement.
- [Investigation history (Chinese)](docs/HISTORY.md) traces the main experiments and decisions.
- [Patch series (Chinese)](patches/README.md) describes patches 0001, 0002, 0003, 0005, and 0006 used on the test machine.
- [Repository maintenance (Chinese)](docs/PUBLISH.md) records publication and update steps.

## Credits and AI disclosure

- **Xecuss** set the goals, performed the Linux and Windows testing, collected the data, checked the visual results, and chose the current setting.
- **GPT-6.1 Sol** contributed to source and patch analysis, data collection tools, review of the data and conclusions, and repository preparation.
- **GLM-5.3** contributed to the initial investigation and experiments. Later review revised some of the early hypotheses.
