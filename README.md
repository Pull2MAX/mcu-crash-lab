# mcu-crash-lab

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-0969da?style=for-the-badge" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-gray?style=for-the-badge" alt="简体中文"></a>
</p>

mcu-crash-lab is an agent skill for triaging Cortex-M crashes. Give it CFSR/HFSR, the fault address registers, the stacked PC/LR and the matching ELF. It names the fault bits that are set and finds where PC and LR point in the source. The repository also has small firmware fixtures. They run in QEMU as regression checks for the analyzer.

## Use

Copy `skills/mcu-crash-lab/` to the directory your agent loads skills from. Each agent puts it somewhere different, so check your agent's docs. Copying the skill does not install the fixture suite. The suite stays in this repository.

Run the analyzer on a dump:

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

`arm-none-eabi-addr2line` must be on PATH.

A dump must contain `CFSR`, `HFSR`, `MMFAR`, `BFAR`, `PC` and `LR`. Give the raw values of the address registers even when their VALID bits are clear. The analyzer then reports those addresses as invalid. `EXC_RETURN`, `xPSR` and `SP` are optional. If one is missing, whatever depends on it (frame type, execution context or pre-exception SP) is reported as unknown, with a caveat.

Register values are read as hex. A bare value such as `CFSR=00008200` is accepted, with a caveat about that assumption. One line can hold several `KEY=VALUE` or `KEY: VALUE` pairs and can end with annotations. The JSON output has separate `cause`, `frame` (basic/extended) and `context` (thread/isr plus exception number) fields. Symbol names are demangled. When addr2line returns multiple frames, the output includes `inline_chain`.

The offline demo needs only Python and addr2line:

    make demo

`examples/offline/` holds a prebuilt ELF from `unmapped_write_busfault`, plus a full QEMU capture and a hand-built thin dump. In the thin dump, CFSR has only IMPRECISERR and BFAR is not valid. Its PC is already past the store. The analyzer warns that PC may not identify the faulting instruction. These examples do not count as QEMU regression matches. A dump can also include `FPCCR`, which can trigger a warning about lazy FP state. Only synthetic unit tests cover this, because the fixture dumper does not capture FPCCR.

## Fixtures

The last real `make test` run recorded 7 QEMU regression matches (`verified_count` in [tests/results.json](tests/results.json)). A stored status of `verified` means the analyzer's decoding agreed with the values measured in QEMU and the fault PC was on the line marked `/* FAULT HERE */`. This is only a regression check. It does not prove the diagnosis is correct. The expected register values were themselves taken from QEMU. The source marker gives a separate check of the PC location.

The 7 scenarios cover 4 distinct mechanisms: a store to an unmapped address, integer division by zero, an undefined instruction and an MPU data permission violation. The remaining fixtures repeat one of these with an extended frame, in ISR context or with escalation.

| Fixture | Code on mps2-an386 | Measured registers/frame | Regression status |
|---|---|---|---|
| unmapped_write_busfault | write to unmapped address 0x60000000 | PRECISERR, BFARVALID | match in QEMU 10.0.13 (mps2-an386) |
| div0_usagefault | integer divide by zero with CCR.DIV_0_TRP set | DIVBYZERO | match in QEMU 10.0.13 (mps2-an386) |
| undefined_instruction_usagefault | execute UDF #0 | UNDEFINSTR | match in QEMU 10.0.13 (mps2-an386) |
| fpu_frame_fault | FP addition, then write to unmapped address 0x60000000 | PRECISERR, BFARVALID, extended frame (EXC_RETURN 0xFFFFFFE9) | match in QEMU 10.0.13 (mps2-an386) |
| mpu_violation | write to buffer at 0x20000000 with MPU read-only permissions | DACCVIOL, MMARVALID | match in QEMU 10.0.13 (mps2-an386) |
| mpu_violation_forced | same buffer write, MEMFAULTENA off | DACCVIOL, MMARVALID, HFSR.FORCED | match in QEMU 10.0.13 (mps2-an386) |
| fault_in_isr_unmapped | write to unmapped address 0x60000000 in SysTick_Handler | PRECISERR, BFARVALID, HFSR.FORCED, exception number 15 | match in QEMU 10.0.13 (mps2-an386) |
| fault_in_isr | write to address 0 in SysTick_Handler | none | not reproduced (address 0 is RAM on mps2-an386, no fault) |

QEMU does not model the write buffer, so the store to 0x60000000 gives a precise BusFault with BFARVALID set. On real Cortex-M3/M4 devices this store to Normal memory is buffered and usually shows up as IMPRECISERR. BFAR is then not valid, and PC has already moved past the store. On the MPS2 AN386 model, address 0 is writable RAM, so the NULL write in `fault_in_isr` does not fault there.

Each fixture has an `expected.json`. It lists the expected function, the line (marked `/* FAULT HERE */` in main.c), the CFSR bits and a `source` label. The label is `qemu_measured`, `hand_built` or `real_device`. A QEMU run adds to `verified_count` only when it matches and the source is `qemu_measured`. `fault_in_isr` keeps its hand-built predictions and the status `not_reproduced`. The saved `dump.txt` files are used by the unit tests and by runs without QEMU. Without QEMU, the runner reports "static analysis only" and counts zero QEMU regression matches.

Limits of these checks:

- `fault_in_isr_unmapped` measures CFSR 0x8200 and HFSR.FORCED. That fits a BusFault that cannot preempt SysTick at priority 0. The checks confirm these bits, exception number 15, EXC_RETURN 0xFFFFFFF1 and a PC in SysTick_Handler. The dumper does not record which handler vector was active, so HardFault labels are inferred from the status bits.
- In the basic and extended frames here, the core registers come first, and the dumper reads PC at SP+0x18. Matching that PC against the marker checks where the dumper reads. The frame size and pre-exception SP calculations have unit tests, but there are no independently measured pre-exception SP values to compare with.
- No fixture covers stack overflow (STKERR/MSTKERR), unaligned access, INVSTATE, IACCVIOL, NOCP, INVPC, IMPRECISERR or a PSP thread frame yet. The hand-built IMPRECISERR demo does not count as coverage. Fixtures are built with GCC at `-O0`. Optimized builds and Keil/IAR images have not been tested.

Some fixtures have a fixed variant: fpu_frame_fault, mpu_violation, mpu_violation_forced, fault_in_isr and fault_in_isr_unmapped. They also build fixed/main.c, which must print DONE. The fixed code just leaves out the faulting operation. It does not test any proposed diagnosis or repair advice.

Scoring a model's crash conclusions against expected.json is planned and has not been done. Nothing here measures model accuracy.

## Test

You need arm-none-eabi-gcc, make, python3 and qemu-system-arm with the mps2-an386 machine.

    make test

This runs the unit tests first. Then it builds every fixture, runs it in QEMU with a 10 s timeout, passes the captured registers to the analyzer and compares the result with `expected.json`.

In the provided workspace environment, run:

    source ~/opt/qemu-env.sh && make clean && make test

## Layout

    skills/mcu-crash-lab/   SKILL.md, scripts/analyze_crash.py, references/
    fixtures/<name>/        main.c, Makefile, expected.json, dump.txt; some have startup.c/link.ld
    fixtures/common/        shared startup.c, link.ld, fault handler and make rules
    tests/                  run_fixtures.py, test_analyzer.py, results.json

The references in `skills/mcu-crash-lab/references/` are drafts and have not been checked against hardware.

## License

MIT, see LICENSE.
