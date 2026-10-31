# mcu-crash-lab

An agent skill for triaging Cortex-M crashes. Give it CFSR/HFSR, the fault address registers, stacked PC/LR and the matching ELF; it names the fault bits and locates PC/LR in the source. The small firmware fixtures exercise instructions and memory accesses on QEMU's MPS2 AN386 model; their captured registers check the analyzer.

## Use

Copy `skills/mcu-crash-lab/` to wherever your agent loads skills from. Install locations differ between agents; check your agent's docs.

Run the analyzer on a dump:

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

It needs `arm-none-eabi-addr2line` on PATH.

For an offline demo with Python and addr2line only:

    make demo

`examples/offline/` contains a prebuilt ELF from `unmapped_write_busfault`, a full QEMU capture and a hand-built thin dump. The thin dump has only IMPRECISERR in CFSR, no BFAR and PC past the store; the analyzer warns that PC may not identify the faulting instruction. These examples add no verified scenarios. Optional `FPCCR` in a dump lets the analyzer warn when an extended frame has lazy FP state still pending.

## Fixtures

7 verified scenarios (from the last `make test`, see `tests/results.json`).

| Fixture | Code on mps2-an386 | Measured fault | Status |
|---|---|---|---|
| unmapped_write_busfault | write to unmapped address 0x60000000 | precise BusFault (PRECISERR, BFARVALID) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| div0_usagefault | integer divide by zero with CCR.DIV_0_TRP set | UsageFault (DIVBYZERO) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| undefined_instruction_usagefault | execute UDF #0 | UsageFault (UNDEFINSTR) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| fpu_frame_fault | FP addition, then write to unmapped address 0x60000000 | BusFault with FPU extended frame (EXC_RETURN 0xFFFFFFE9) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| mpu_violation | write to buffer at 0x20000000 with MPU read-only permissions | MemManage (DACCVIOL, MMARVALID) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| mpu_violation_forced | same buffer write, MEMFAULTENA off | HardFault with HFSR FORCED | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| fault_in_isr_unmapped | write to unmapped address 0x60000000 in SysTick_Handler | BusFault escalated to HardFault (FORCED) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| fault_in_isr | write to address 0 in SysTick_Handler | none | not reproduced (address 0 is RAM on mps2-an386, no fault) |

The BusFault fixture writes to unmapped address 0x60000000. On the MPS2 AN386 model address 0 is writable RAM, so the NULL write in `fault_in_isr` does not fault there.

Each fixture has `expected.json` with the expected function, line (marked `/* FAULT HERE */` in main.c), CFSR bits and a `source` label: `qemu_measured`, `hand_built` or `real_device`. Only matching QEMU runs with source `qemu_measured` count as verified. `fault_in_isr` keeps hand-built predictions and status `not_reproduced`. `dump.txt` is the dump captured from the QEMU run, used by the unit tests and as the input when QEMU is missing. Without QEMU the runner reports "static analysis only" and counts zero verified scenarios.

Notes on measured values that differ from tasks/batch2.md:

- fault_in_isr_unmapped: the spec predicted a plain BusFault. QEMU gives CFSR 0x8200 with HFSR FORCED, because SysTick and BusFault both run at priority 0, so the BusFault cannot preempt and escalates. xPSR exception number 15, EXC_RETURN 0xFFFFFFF1 and PC in SysTick_Handler match the spec.
- fpu_frame_fault: the stacked PC is at SP+0x18 in both basic and extended frames; the FP registers are stored after the core registers. The spec's wording about skipping S0-S15 before the PC is wrong. EXC_RETURN and the decoded function match.
- fault_in_isr keeps the predicted values in expected.json and is reported as NOT REPRODUCED by the test runner. It is not counted as verified.

Fixtures marked with a fixed variant (fpu_frame_fault, mpu_violation, mpu_violation_forced, fault_in_isr, fault_in_isr_unmapped) also build fixed/main.c, which must print DONE.

Scoring a model's crash conclusions against expected.json is planned, not done. Nothing here measures model accuracy.

## Test

Needs arm-none-eabi-gcc, make, python3 and qemu-system-arm with the mps2-an386 machine.

    make test

This runs the unit tests, then builds every fixture, runs it in QEMU with a 10 s timeout, feeds the captured registers to the analyzer and compares the result with `expected.json`.

## Layout

    skills/mcu-crash-lab/   SKILL.md, scripts/analyze_crash.py, references/
    fixtures/<name>/        main.c, startup.c, link.ld, Makefile, expected.json, dump.txt
    fixtures/common/        shared startup and fault handler, shared make rules
    tests/                  run_fixtures.py, test_analyzer.py, results.json

The references in `skills/mcu-crash-lab/references/` are drafts and have not been checked against hardware.

## License

MIT, see LICENSE.
