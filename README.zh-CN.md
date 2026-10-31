# mcu-crash-lab

用于分析 Cortex-M 崩溃的 agent skill。提供 CFSR/HFSR、故障地址寄存器、压栈的 PC/LR 以及对应的 ELF，它会给出置位的故障位和出错的源码行。这里的每个 fixture 都是一个故意崩溃的小固件，用真实的故障来检验分析脚本，而不是手写的寄存器转储。

## 使用

把 `skills/mcu-crash-lab/` 复制到你的 agent 加载 skill 的目录。各 agent 的安装位置不同，请查看对应 agent 的文档。

分析一份转储：

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

需要 PATH 中有 `arm-none-eabi-addr2line`。

## Fixtures

已验证场景 3 个（来自最近一次 `make test`，见 `tests/results.json`）。

| Fixture | 故障 | 状态 |
|---|---|---|
| unmapped_write_busfault | 精确 BusFault（PRECISERR、BFARVALID） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| div0_usagefault | UsageFault（DIVBYZERO，已置 CCR.DIV_0_TRP） | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| undefined_instruction_usagefault | UsageFault（UNDEFINSTR） | verified in qemu-system-arm 10.0.13 (mps2-an386) |

BusFault fixture 写的是 0x60000000，不是 NULL。MPS2 AN386 模型上地址 0 是 RAM，写 NULL 不会触发故障。在地址 0 为 flash 或未映射的真实芯片上，写 NULL 会得到相同的 PRECISERR/BFARVALID，但这个 fixture 测的不是这种情况。

每个 fixture 的 `expected.json` 写明出错函数、行号（main.c 中标有 `/* FAULT HERE */`）和 CFSR 位。`dump.txt` 是 QEMU 运行时抓到的转储，供单元测试使用，没有 QEMU 时也作为输入。没有 QEMU 时测试脚本报告 "static analysis only"，已验证数为 0。

## 测试

需要 arm-none-eabi-gcc、make、python3，以及支持 mps2-an386 的 qemu-system-arm。

    make test

先跑单元测试，再逐个构建 fixture，在 QEMU 中运行（超时 10 秒），把抓到的寄存器交给分析脚本，并与 `expected.json` 比较。

## 许可

MIT，见 LICENSE。
