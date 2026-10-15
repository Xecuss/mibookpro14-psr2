# GitHub发布准备

建议沿用充电阈值项目 `Xecuss/mibookpro14-powerlimit` 的命名，目标仓库为 `Xecuss/mibookpro14-psr2`。本目录是独立仓库，原调查目录不作为Git根目录。

已整理中文入口、使用/构建/回退、原理、功耗条件与限制、简要过程、5个实测补丁、只读Linux采集工具、离线检查，以及6轮共258点规范化功耗数据与寄存器节选。104为用户选定的日常候选；所有“根因未明”“80也能工作”“功耗未定赢家”的限制保留。

不包含完整内核树、构建模块、私钥、Windows驱动/可执行程序、崩溃转储、Bing壁纸、完整机器日志或上游交流包。公开数据按字段导出，原始来源指纹保留，不能把这些节选当作完整原始采集。运行采集工具生成的新results默认不跟踪。

本次请求是准备推送；本地完成不代表远端已创建或已发布。创建GitHub仓库时使用上述名称，选定可见性，不预置README、LICENSE或.gitignore。远端已有不同内容时应先核对，以下命令不使用force。

```bash
git status --short
make check
git remote -v
git push -u origin main
```

若尚无origin：

```bash
git remote add origin git@github.com:Xecuss/mibookpro14-psr2.git
```

建议仓库描述：

```text
Experimental PSR2 selective-update alignment workaround for Xiaomi Book Pro 14 2026, with Windows reference and power measurements.
```

这是分享本机实验结果，不是上游补丁投稿、bug报告或quirk扩展。发布不会自动通知原上游问题参与者。
