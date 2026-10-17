# 构建、安装与回退

## 范围

完整功能与功耗实验来自Fedora `7.2.9-200.fc44.x86_64`；`7.2.10-200.fc44.x86_64`已完成匹配源码构建、签名安装、启动及PSR2/深睡配置核对，用户报告日常无花屏。两版各有独立的5文件输入/输出指纹，其他版本需要重新适配和构建。本项目不是一个只安装kernel-devel即可make的独立驱动，也没有经验证的自动DKMS安装流程。

已有本次0006测试模块的原机器无需重复本节，启动时改回104即可。本仓库不提供二进制模块、MOK私钥或原调查中的内核源码树。

## 准备匹配的完整内核构建树

使用目标发行版同一内核构建的完整源码、发行版补丁、配置、生成头文件和符号版本；保留发行版ABI相关配置。只有同样的版本字符串不保证模块结构与ABI完全一致。单纯 `modules_prepare` 不会在CONFIG_MODVERSIONS启用时生成所需的Module.symvers，见[Linux Kbuild说明](https://docs.kernel.org/kbuild/modules.html)。

以下假定你已通过发行版的内核构建流程准备好可构建树，并将 `KERNEL_SRC` 设置为它的绝对路径。仓库不自动下载源码、不改发行版配置、不关闭BTF或签名检查。

```bash
export KERNEL_SRC=/absolute/path/to/prepared/linux-7.2.10
python3 scripts/apply-patches.py --check "$KERNEL_SRC"
python3 scripts/apply-patches.py "$KERNEL_SRC"
```

脚本用SHA256限定已核对的5个原文件，先在临时副本应用整套补丁，再核对结果与实机版本的SHA256，全部通过才写回所选树。原始补丁上下文保留GNU patch最多2行的容差，但输入和输出文件都必须精确匹配，不能借容差接受不同源码。它不重命名内核、不构建或安装模块；已打过补丁的树会拒绝重复应用。请在专门的源码副本中运行，保留原树作为回退。

## 构建

```bash
make -C "$KERNEL_SRC" -s kernelrelease
make -C "$KERNEL_SRC" -j8 M=drivers/gpu/drm/xe modules
mkdir -p build
cp -- "$KERNEL_SRC/drivers/gpu/drm/xe/xe.ko" build/xe.ko
modinfo -F vermagic build/xe.ko
modinfo -p build/xe.ko
```

kernelrelease和vermagic必须匹配目标内核；应能看到psr2_su_y_alignment参数。不要把其他内核的模块装进当前内核。原调查构建曾通过、无编译警告/错误；BTF因未提供vmlinux跳过，没有通过关闭DEBUG_INFO_BTF来改变ABI。本仓库的离线CI不编译完整内核，也不代表新构建已经过实机验证。

## 签名与安装（Fedora实测路径）

以下命令为显式指定的目标内核安装优先加载的xe模块并重建其initramfs；不卸载当前图形驱动、不自动重启、不修改GRUB。可以仍运行旧内核，为已安装的新内核准备模块，不能用uname -r代替目标版本。

```bash
export PSR_TARGET_KERNEL=7.2.10-200.fc44.x86_64
test "$(modinfo -F vermagic build/xe.ko | cut -d ' ' -f 1)" = "$PSR_TARGET_KERNEL"
```

确认vermagic的版本与目标一致，且目标内核及对应kernel-devel已安装，再继续。使用本机已有且证书已被信任的模块签名密钥；路径由使用者填写，私钥不放仓库。签名后不要再strip该文件。原始机制见[内核模块签名文档](https://docs.kernel.org/admin-guide/module-signing.html)。

```bash
export MOK_KEY=/absolute/path/to/existing/MOK.priv
export MOK_CERT=/absolute/path/to/existing/MOK.der
cp -- build/xe.ko build/xe-signed.ko
sudo "/usr/src/kernels/$PSR_TARGET_KERNEL/scripts/sign-file" sha512 "$MOK_KEY" "$MOK_CERT" build/xe-signed.ko
modinfo -F signer build/xe-signed.ko
```

确认签名成功，给本次操作创建独立备份目录，并保存原updates覆盖是否存在。若原路径是符号链接或另有模块管理工具接管，先按原管理方式处理，不覆盖它。

```bash
export PSR_BACKUP_DIR="$PWD/build/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -- "$PSR_BACKUP_DIR"
printf '%s\n' "$PSR_TARGET_KERNEL" > "$PSR_BACKUP_DIR/kernel-release"
modinfo -k "$PSR_TARGET_KERNEL" -n xe > "$PSR_BACKUP_DIR/original-module-path"
sudo test ! -L "/lib/modules/$PSR_TARGET_KERNEL/updates/xe.ko"
if sudo test -e "/lib/modules/$PSR_TARGET_KERNEL/updates/xe.ko"; then
    sudo cp -- "/lib/modules/$PSR_TARGET_KERNEL/updates/xe.ko" "$PSR_BACKUP_DIR/xe-before.ko"
    touch "$PSR_BACKUP_DIR/had-updates-override"
fi
sudo install -D -m 644 build/xe-signed.ko "/lib/modules/$PSR_TARGET_KERNEL/updates/xe.ko"
sudo depmod -a "$PSR_TARGET_KERNEL"
sudo dracut -f --kver "$PSR_TARGET_KERNEL"
modinfo -k "$PSR_TARGET_KERNEL" -n xe
```

必须确认每一步成功，且modinfo解析到刚安装的updates/xe.ko，再进入下一次启动。在GRUB临时加入 `xe.psr2_su_y_alignment=104`，删除强制PSR1及旧CFF门槛；下一次启动后按[复测方法](TESTING.md)确认实际PSR2、网格、SU与plane范围。硬件仍运行原模块，直到重启。

## 回退

仅删除网格参数或设0会恢复原生区域逻辑，并不移除测试模块；花屏可能回来。需要临时停止PSR2时，GRUB加 `xe.enable_psr=1` 可退回PSR1；本机已测，但这不是PSR2修复方案。

完整模块回退先填上本次保存的备份目录，再检查备份对应内核与要回退的目标内核一致。若此后又换过模块，先核对实际文件，不能用旧备份覆盖新的安装。

```bash
export PSR_TARGET_KERNEL=7.2.10-200.fc44.x86_64
export PSR_BACKUP_DIR=/absolute/path/to/this-install-backup
test "$(cat "$PSR_BACKUP_DIR/kernel-release")" = "$PSR_TARGET_KERNEL"
if test -f "$PSR_BACKUP_DIR/had-updates-override"; then
    sudo install -D -m 644 "$PSR_BACKUP_DIR/xe-before.ko" "/lib/modules/$PSR_TARGET_KERNEL/updates/xe.ko"
else
    sudo rm -- "/lib/modules/$PSR_TARGET_KERNEL/updates/xe.ko"
fi
sudo depmod -a "$PSR_TARGET_KERNEL"
sudo dracut -f --kver "$PSR_TARGET_KERNEL"
modinfo -k "$PSR_TARGET_KERNEL" -n xe
```

删除本项目的启动参数，重启后才使用回退模块；若无法进入当前图形会话，可从保留的发行版内核启动。7.2.10的安装与签名由用户执行，当前已启动该模块；回退命令未在此次升级中执行。新版本验证记录见[内核升级](UPGRADING.md)。
