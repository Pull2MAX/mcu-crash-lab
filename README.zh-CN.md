# mcu-crash-lab

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-gray?style=for-the-badge" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-0969da?style=for-the-badge" alt="简体中文"></a>
</p>

用于分析 Cortex-M 崩溃的 agent skill。提供 CFSR/HFSR、故障地址寄存器、压栈的 PC/LR 以及对应的 ELF，它会给出置位的故障位和 PC/LR 对应的源码位置。小固件 fixture 用于对分析脚本进行 QEMU 回归检查。

## 使用

把 `skills/mcu-crash-lab/` 复制到你的 agent 加载 skill 的目录。各 agent 的安装位置不同，请查看对应 agent 的文档。fixture 测试套件保留在本仓库中，复制 skill 不会安装这套测试。

分析一份转储：

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

需要 PATH 中有 `arm-none-eabi-addr2line`。

转储必须包含 `CFSR`、`HFSR`、`MMFAR`、`BFAR`、`PC` 和 `LR`。即使地址寄存器的 VALID 位未置位，也要提供原始值；分析脚本会将这些地址标为无效。`EXC_RETURN`、`xPSR` 和 `SP` 可选，缺少时依赖它们的帧类型、执行上下文或异常前 SP 显示为未知，并给出提示。

寄存器值按十六进制解析。`CFSR=00008200` 这样的无前缀值也可接受，但会提示这一假设。一行可包含多组 `KEY=VALUE` 或 `KEY: VALUE`，也可带尾部注释。JSON 分别报告 `cause`、`frame`（basic/extended）和 `context`（thread/isr 及异常号）。符号化会还原 C++ 名称，addr2line 返回多帧时还会包含 `inline_chain`。

离线演示只需要 Python 和 addr2line：

    make demo

`examples/offline/` 包含从 `unmapped_write_busfault` 构建的 ELF、完整的 QEMU 转储和手工构造的精简转储。精简转储的 CFSR 仅含 IMPRECISERR，没有有效 BFAR，PC 位于 store 指令之后；分析脚本会提示 PC 可能不是故障指令。这些示例不增加 QEMU 回归匹配数。可选的 `FPCCR` 可触发延迟保存 FP 状态的提示；这项行为只有合成数据单元测试，因为 fixture 的转储程序不采集 FPCCR。

## Fixtures

最近一次实际执行的 `make test` 记录了 7 个 QEMU 回归匹配（[tests/results.json](tests/results.json) 中的 `verified_count`）。这里保存的 `verified` 状态表示：分析脚本的解码与 QEMU 实测值一致，且故障 PC 行号匹配 `/* FAULT HERE */` 标记。这是回归检查，不是诊断正确性的证明。寄存器预期值本身来自 QEMU；源码标记另外检查 PC 的位置。

这 7 个场景覆盖 4 种不同机制：写未映射地址、整数除零、未定义指令和 MPU 数据权限违规。扩展帧、ISR 上下文及升级异常只是这些机制的变体。

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

QEMU 不模拟写缓冲：写 0x60000000 产生精确 BusFault，BFARVALID 置位。真实 Cortex-M3/M4 对这种可缓冲 Normal 内存的写操作通常报告 IMPRECISERR，没有有效 BFAR，PC 也已越过 store。MPS2 AN386 模型上地址 0 是可写 RAM，因此 `fault_in_isr` 中的 NULL 写操作不会触发故障。

每个 fixture 的 `expected.json` 写明预期函数、行号（main.c 中标有 `/* FAULT HERE */`）、CFSR 位和 `source` 标签：`qemu_measured`、`hand_built` 或 `real_device`。只有来源为 `qemu_measured` 且与预期匹配的 QEMU 运行才计入 `verified_count`。`fault_in_isr` 保留手工预测值和 `not_reproduced` 状态。保存的 `dump.txt` 用于单元测试及没有 QEMU 时的运行。没有 QEMU 时测试脚本报告 "static analysis only"，QEMU 回归匹配数为 0。

这些检查的局限：

- `fault_in_isr_unmapped` 测得 CFSR 0x8200 和 HFSR.FORCED，与 BusFault 无法抢占优先级为 0 的 SysTick 相符。检查确认了这些位、异常号 15、EXC_RETURN 0xFFFFFFF1 以及 PC 位于 SysTick_Handler。转储程序不采集当前 handler 向量，所以 HardFault 标签是根据状态位推断的。
- 在这些基本帧和扩展帧中，核心寄存器在前，转储程序从 SP+0x18 读取 PC。将该 PC 与标记匹配，检查的是转储程序读取的位置。帧大小及异常前 SP 计算有单元测试，但没有独立测得的异常前 SP 真值。
- 尚无 fixture 覆盖栈溢出（STKERR/MSTKERR）、非对齐访问、INVSTATE、IACCVIOL、NOCP、INVPC、IMPRECISERR 或 PSP 线程帧。手工构造的 IMPRECISERR 演示不填补这一空白。fixture 使用 GCC 和 `-O0`；优化构建及 Keil/IAR 镜像未经测试。

带 fixed 变体的 fixture（fpu_frame_fault、mpu_violation、mpu_violation_forced、fault_in_isr、fault_in_isr_unmapped）还会构建 fixed/main.c，要求打印 DONE。这些变体省去了故障操作，不验证提出的诊断或修复建议。

用 expected.json 评估模型的崩溃分析结论是计划中的工作，尚未进行，这里没有任何模型准确率的测量。

## 测试

需要 arm-none-eabi-gcc、make、python3，以及支持 mps2-an386 的 qemu-system-arm。

    make test

先跑单元测试，再逐个构建 fixture，在 QEMU 中运行（超时 10 秒），把抓到的寄存器交给分析脚本，并与 `expected.json` 比较。

在提供的工作区环境中运行：

    source ~/opt/qemu-env.sh && make clean && make test

## 目录

    skills/mcu-crash-lab/   SKILL.md、scripts/analyze_crash.py、references/
    fixtures/<name>/        main.c、Makefile、expected.json、dump.txt；部分自带 startup.c/link.ld
    fixtures/common/        共享 startup.c、link.ld、故障处理程序及 make 规则
    tests/                  run_fixtures.py、test_analyzer.py、results.json

`skills/mcu-crash-lab/references/` 中的参考资料是草稿，未经硬件验证。

## 许可

MIT，见 LICENSE。
