# 第三方来源与声明

补丁上下文和tests/alignment-check.c中的对齐函数来自Linux的Intel显示代码，修改前文件为MIT许可。原版权声明包括Intel Corporation ©2014（intel_psr.c）、©2020（intel_vrr.c及intel_display_debugfs.c）、©2023（intel_display_params.c/h）；本项目不改变其原许可。

intel_psr.c原声明：

```text
/*
 * Copyright © 2014 Intel Corporation
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice (including the next
 * paragraph) shall be included in all copies or substantial portions of the
 * Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 */
```

intel_vrr.c原头部：

```text
// SPDX-License-Identifier: MIT
/*
 * Copyright © 2020 Intel Corporation
 *
 */
```

完整Linux内核、固件和发行版组件不随仓库分发。Windows数据仅为用户采集的事实性遥测/寄存器节选；不包含RWEverything程序、驱动或其他第三方二进制。
