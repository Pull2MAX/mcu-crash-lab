# mcu-crash-lab

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-gray?style=for-the-badge" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-0969da?style=for-the-badge" alt="简体中文"></a>
</p>

mcu-crash-lab 是一个排查 Cortex-M 崩溃用的 agent skill。把 CFSR/HFSR、故障地址寄存器、压栈的 PC/LR 和对应的 ELF 交给它，它会列出置位的故障位，并找到 PC 和 LR 在源码里的位置。仓库里还有一些小固件 fixture，在 QEMU 里运行，作为分析脚本的回归检查。

## 使用

把 `skills/mcu-crash-lab/` 复制到你的 agent 加载 skill 的目录。各家 agent 的目录不一样，具体看它的文档。复制 skill 不会顺带装上 fixture 测试套件，这套测试留在本仓库里。

分析一份转储：

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

PATH 里要能找到 `arm-none-eabi-addr2line`。

转储里必须有 `CFSR`、`HFSR`、`MMFAR`、`BFAR`、`PC` 和 `LR`。地址寄存器的 VALID 位没置上，也照样给出原始值，分析脚本会把这些地址标为无效。`EXC_RETURN`、`xPSR` 和 `SP` 可以不给。缺了哪一项，依赖它的帧类型、执行上下文或异常前 SP 就显示为未知，并附一条提示。

寄存器值按十六进制解析。`CFSR=00008200` 这种不带前缀的写法也能用，输出里会附一条提示，说明做了这个假设。一行里可以写多组 `KEY=VALUE` 或 `KEY: VALUE`，行尾还可以带注释。JSON 输出里，`cause`、`frame`（basic/extended）和 `context`（thread/isr 及异常号）是分开的字段。符号名会还原成 C++ 原名。addr2line 返回多帧时，输出里会带上 `inline_chain`。

离线演示只需要 Python 和 addr2line：

    make demo

`examples/offline/` 里有一个从 `unmapped_write_busfault` 预先构建好的 ELF，另外有一份完整的 QEMU 转储和一份手工写的精简转储。精简转储里 CFSR 只有 IMPRECISERR，BFAR 无效。它的 PC 已经越过了 store 指令。分析脚本会提示 PC 可能不是故障指令。这些示例不计入 QEMU 回归匹配数。转储里还可以加上 `FPCCR`，用来触发 FP 状态延迟保存的提示。这一项只有合成数据的单元测试，因为 fixture 的转储程序不采集 FPCCR。

## Fixtures

最近一次实际运行的 `make test` 记录了 7 个 QEMU 回归匹配（见 [tests/results.json](tests/results.json) 里的 `verified_count`）。保存下来的 `verified` 状态表示：分析脚本的解码结果和 QEMU 实测值一致，而且故障 PC 落在标有 `/* FAULT HERE */` 的那一行。这只是回归检查，证明不了诊断是对的。寄存器预期值本身就取自 QEMU。源码标记另外检查了 PC 的位置。

这 7 个场景涉及 4 种不同的机制：写未映射地址、整数除零、未定义指令和 MPU 数据权限违规。其余 fixture 是在其中某一种上加了扩展帧、放进 ISR 上下文或引发异常升级。

| Fixture | mps2-an386 上执行的操作 | 实测寄存器/帧 | 回归状态 |
|---|---|---|---|
| unmapped_write_busfault | 写未映射地址 0x60000000 | PRECISERR、BFARVALID | QEMU 10.0.13 (mps2-an386) 匹配 |
| div0_usagefault | 置 CCR.DIV_0_TRP 后执行整数除零 | DIVBYZERO | QEMU 10.0.13 (mps2-an386) 匹配 |
| undefined_instruction_usagefault | 执行 UDF #0 | UNDEFINSTR | QEMU 10.0.13 (mps2-an386) 匹配 |
| fpu_frame_fault | 浮点加法后写未映射地址 0x60000000 | PRECISERR、BFARVALID、扩展帧（EXC_RETURN 0xFFFFFFE9） | QEMU 10.0.13 (mps2-an386) 匹配 |
| mpu_violation | 写 MPU 设为只读的 buffer，地址 0x20000000 | DACCVIOL、MMARVALID | QEMU 10.0.13 (mps2-an386) 匹配 |
| mpu_violation_forced | 同样的 buffer 写操作，未开 MEMFAULTENA | DACCVIOL、MMARVALID、HFSR.FORCED | QEMU 10.0.13 (mps2-an386) 匹配 |
| fault_in_isr_unmapped | SysTick_Handler 中写未映射地址 0x60000000 | PRECISERR、BFARVALID、HFSR.FORCED、异常号 15 | QEMU 10.0.13 (mps2-an386) 匹配 |
| fault_in_isr | SysTick_Handler 中写地址 0 | 无 | not reproduced（mps2-an386 上地址 0 是 RAM，不产生故障） |

QEMU 不模拟写缓冲，所以写 0x60000000 得到的是精确 BusFault，BFARVALID 置位。在真实的 Cortex-M3/M4 上，这次写的是 Normal 内存，会进写缓冲，通常报成 IMPRECISERR。这时 BFAR 无效，PC 也已经越过了 store。MPS2 AN386 模型上地址 0 是可写 RAM，因此 `fault_in_isr` 里的 NULL 写在这里不会触发故障。

每个 fixture 都有一个 `expected.json`，里面写着预期函数、行号（main.c 里用 `/* FAULT HERE */` 标出）、CFSR 位和 `source` 标签。标签取值为 `qemu_measured`、`hand_built` 或 `real_device`。QEMU 运行结果与预期一致，并且来源是 `qemu_measured`，才计入 `verified_count`。`fault_in_isr` 保留手工预测值，状态是 `not_reproduced`。保存的 `dump.txt` 给单元测试用，没有 QEMU 时也拿它来跑。没有 QEMU 时，测试脚本报告 "static analysis only"，QEMU 回归匹配数为 0。

这些检查的局限：

- `fault_in_isr_unmapped` 测得 CFSR 0x8200 和 HFSR.FORCED，这和 BusFault 无法抢占优先级为 0 的 SysTick 的情况相符。检查确认了这些位、异常号 15、EXC_RETURN 0xFFFFFFF1，以及 PC 位于 SysTick_Handler 内。转储程序不记录当时进入的是哪个 handler 向量，所以 HardFault 标签是从状态位推断出来的。
- 这里的基本帧和扩展帧都是核心寄存器在前，转储程序从 SP+0x18 读取 PC。拿这个 PC 去对照标记，检查的是转储程序读取的位置。帧大小和异常前 SP 的计算有单元测试，但没有独立测得的异常前 SP 值可以对照。
- 栈溢出（STKERR/MSTKERR）、非对齐访问、INVSTATE、IACCVIOL、NOCP、INVPC、IMPRECISERR 和 PSP 线程帧目前都还没有 fixture。手工构造的 IMPRECISERR 演示不算覆盖。fixture 用 GCC 以 `-O0` 构建，优化构建和 Keil/IAR 镜像都没有测过。

有些 fixture 带 fixed 变体：fpu_frame_fault、mpu_violation、mpu_violation_forced、fault_in_isr 和 fault_in_isr_unmapped。它们还会构建 fixed/main.c，要求打印 DONE。fixed 代码只是去掉了出错的那一步操作，不检验任何诊断或修复建议。

用 expected.json 给模型的崩溃分析结论打分已列入计划，还没有做。这里没有任何测量模型准确率的内容。

## 测试

需要 arm-none-eabi-gcc、make、python3，以及支持 mps2-an386 机型的 qemu-system-arm。

    make test

它先跑单元测试，然后逐个构建 fixture，在 QEMU 中运行（超时 10 秒），把抓到的寄存器交给分析脚本，再和 `expected.json` 比对。

在提供的工作区环境里这样运行：

    source ~/opt/qemu-env.sh && make clean && make test

## 目录

    skills/mcu-crash-lab/   SKILL.md、scripts/analyze_crash.py、references/
    fixtures/<name>/        main.c、Makefile、expected.json、dump.txt；部分自带 startup.c/link.ld
    fixtures/common/        共享 startup.c、link.ld、故障处理程序及 make 规则
    tests/                  run_fixtures.py、test_analyzer.py、results.json

`skills/mcu-crash-lab/references/` 里的参考资料还是草稿，没有在硬件上核对过。

## 许可

MIT，见 LICENSE。
