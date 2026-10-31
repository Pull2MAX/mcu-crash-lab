# mcu-crash-lab

用于分析 Cortex-M 崩溃的 agent skill。提供 CFSR/HFSR、故障地址寄存器、压栈的 PC/LR 以及对应的 ELF，它会给出置位的故障位和 PC/LR 对应的源码位置。这些小固件 fixture 在 QEMU 的 MPS2 AN386 模型上执行特定指令和内存访问，用捕获的寄存器检验分析脚本。

## 使用

把 `skills/mcu-crash-lab/` 复制到你的 agent 加载 skill 的目录。各 agent 的安装位置不同，请查看对应 agent 的文档。

分析一份转储：

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

需要 PATH 中有 `arm-none-eabi-addr2line`。

离线演示只需要 Python 和 addr2line：

    make demo

`examples/offline/` 包含从 `unmapped_write_busfault` 构建的 ELF、完整的 QEMU 转储和手工构造的精简转储。精简转储的 CFSR 仅含 IMPRECISERR，不含 BFAR，PC 位于 store 指令之后；分析脚本会提示 PC 可能不是故障指令。这些示例不增加已验证场景数。转储可选填 `FPCCR`，用于提示扩展帧中的 FP 寄存器因延迟压栈尚未保存。

## Fixtures

已验证场景 7 个（来自最近一次 `make test`，见 `tests/results.json`）。

| Fixture | mps2-an386 上执行的操作 | 实测故障 | 状态 |
|---|---|---|---|
| unmapped_write_busfault | 写未映射地址 0x60000000 | 精确 BusFault（PRECISERR、BFARVALID） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| div0_usagefault | 置 CCR.DIV_0_TRP 后执行整数除零 | UsageFault（DIVBYZERO） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| undefined_instruction_usagefault | 执行 UDF #0 | UsageFault（UNDEFINSTR） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| fpu_frame_fault | 浮点加法后写未映射地址 0x60000000 | BusFault，FPU 扩展栈帧（EXC_RETURN 0xFFFFFFE9） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| mpu_violation | 写 MPU 设为只读的 buffer，地址 0x20000000 | MemManage（DACCVIOL、MMARVALID） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| mpu_violation_forced | 同样的 buffer 写操作，未开 MEMFAULTENA | HardFault，HFSR FORCED | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| fault_in_isr_unmapped | SysTick_Handler 中写未映射地址 0x60000000 | BusFault 升级为 HardFault（FORCED） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| fault_in_isr | SysTick_Handler 中写地址 0 | 无 | not reproduced（mps2-an386 上地址 0 是 RAM，不产生故障） |

BusFault fixture 写未映射地址 0x60000000。MPS2 AN386 模型上地址 0 是可写 RAM，因此 `fault_in_isr` 中的 NULL 写操作不会触发故障。

每个 fixture 的 `expected.json` 写明预期函数、行号（main.c 中标有 `/* FAULT HERE */`）、CFSR 位和 `source` 标签：`qemu_measured`、`hand_built` 或 `real_device`。只有来源为 `qemu_measured` 且与预期匹配的 QEMU 运行才计入已验证数。`fault_in_isr` 保留手工预测值和 `not_reproduced` 状态。`dump.txt` 是 QEMU 运行时抓到的转储，供单元测试使用，没有 QEMU 时也作为输入。没有 QEMU 时测试脚本报告 "static analysis only"，已验证数为 0。

与 tasks/batch2.md 预测不一致的实测值：

- fault_in_isr_unmapped：预测为普通 BusFault。QEMU 实测 CFSR 0x8200 且 HFSR FORCED，原因是 SysTick 和 BusFault 优先级都是 0，BusFault 无法抢占，于是升级为 HardFault。xPSR 异常号 15、EXC_RETURN 0xFFFFFFF1、PC 位于 SysTick_Handler，与预测一致。
- fpu_frame_fault：基本帧和扩展帧中压栈的 PC 都在 SP+0x18，FP 寄存器存放在核心寄存器之后。规格中"跳过 S0-S15 后才是 PC"的说法不对。EXC_RETURN 和解析出的函数与预测一致。
- fault_in_isr 的 expected.json 保留预测值，测试脚本报告为 NOT REPRODUCED，不计入已验证数。

带 fixed 变体的 fixture（fpu_frame_fault、mpu_violation、mpu_violation_forced、fault_in_isr、fault_in_isr_unmapped）还会构建 fixed/main.c，要求打印 DONE。

用 expected.json 评估模型的崩溃分析结论是计划中的工作，尚未进行，这里没有任何模型准确率的测量。

## 测试

需要 arm-none-eabi-gcc、make、python3，以及支持 mps2-an386 的 qemu-system-arm。

    make test

先跑单元测试，再逐个构建 fixture，在 QEMU 中运行（超时 10 秒），把抓到的寄存器交给分析脚本，并与 `expected.json` 比较。

## 许可

MIT，见 LICENSE。
