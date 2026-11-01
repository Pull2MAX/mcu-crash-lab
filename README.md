# mcu-crash-lab

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-0969da?style=for-the-badge" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-gray?style=for-the-badge" alt="简体中文"></a>
</p>

An agent skill for triaging Cortex-M crashes. Give it CFSR/HFSR, the fault address registers, stacked PC/LR and the matching ELF; it names the fault bits and locates PC/LR in the source. Small firmware fixtures provide QEMU regression checks for the analyzer.

## Use

Copy `skills/mcu-crash-lab/` to wherever your agent loads skills from. Install locations differ between agents; check your agent's docs. The fixture suite stays in this repository; copying the skill does not install it.

Run the analyzer on a dump:

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

It needs `arm-none-eabi-addr2line` on PATH.

Required dump fields are `CFSR`, `HFSR`, `MMFAR`, `BFAR`, `PC` and `LR`. Supply the raw address register values even when their VALID bits are clear; the analyzer reports those addresses as invalid. `EXC_RETURN`, `xPSR` and `SP` are optional. Missing fields leave the dependent frame type, execution context or pre-exception SP unknown, with a caveat.

Register values are hexadecimal. Bare values such as `CFSR=00008200` are accepted with an assumption caveat. Multiple `KEY=VALUE` or `KEY: VALUE` pairs may share a line and have trailing annotations. JSON reports `cause`, `frame` (basic/extended) and `context` (thread/isr plus exception number) separately. Symbolization uses demangling and includes `inline_chain` when addr2line returns multiple frames.

For an offline demo with Python and addr2line only:

    make demo

`examples/offline/` contains a prebuilt ELF from `unmapped_write_busfault`, a full QEMU capture and a hand-built thin dump. The thin dump has only IMPRECISERR in CFSR, no valid BFAR and PC past the store; the analyzer warns that PC may not identify the faulting instruction. These examples add no QEMU regression matches. Optional `FPCCR` can trigger a lazy FP state warning; this has synthetic unit tests only, since the fixture dumper does not capture FPCCR.

## Fixtures

The last real `make test` recorded 7 QEMU regression matches (`verified_count` in [tests/results.json](tests/results.json)). Here, the stored status `verified` means the analyzer decoding agrees with values measured in QEMU and the fault PC line matches the `/* FAULT HERE */` marker. This is a regression check, not proof of correct diagnosis. The register expectations themselves came from QEMU; the source marker supplies a separate check of the PC location.

These 7 scenarios cover 4 distinct mechanisms: an unmapped store, integer division by zero, an undefined instruction and an MPU data permission violation. Extended frames, ISR context and escalation exercise variations of those mechanisms.

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

QEMU does not model the write buffer: the store to 0x60000000 produces a precise BusFault with BFARVALID. Real Cortex-M3/M4 devices usually report IMPRECISERR for this buffered Normal-memory store, with no valid BFAR and PC already past the store. On the MPS2 AN386 model address 0 is writable RAM, so the NULL write in `fault_in_isr` does not fault there.

Each fixture has `expected.json` with the expected function, line (marked `/* FAULT HERE */` in main.c), CFSR bits and a `source` label: `qemu_measured`, `hand_built` or `real_device`. Only matching QEMU runs with source `qemu_measured` contribute to `verified_count`. `fault_in_isr` keeps hand-built predictions and status `not_reproduced`. Saved `dump.txt` files supply unit tests and runs without QEMU. Without QEMU the runner reports "static analysis only" and counts zero QEMU regression matches.

Limits of these checks:

- `fault_in_isr_unmapped` measures CFSR 0x8200 and HFSR.FORCED, consistent with a BusFault unable to preempt SysTick at priority 0. The checks establish these bits, exception number 15, EXC_RETURN 0xFFFFFFF1 and PC in SysTick_Handler. The dumper does not capture the active handler vector, so HardFault labels are inferred from status bits.
- In these basic and extended frames, the core registers come first and the dumper reads PC at SP+0x18. Matching that PC to the marker checks the dumper's location. Frame size and pre-exception SP calculations have unit tests, without independently measured pre-exception SP values.
- There are no fixtures yet for stack overflow (STKERR/MSTKERR), unaligned access, INVSTATE, IACCVIOL, NOCP, INVPC, IMPRECISERR or a PSP thread frame. The hand-built IMPRECISERR demo does not fill that gap. Fixtures use GCC at `-O0`; optimized builds and Keil/IAR images are untested.

Fixtures with a fixed variant (fpu_frame_fault, mpu_violation, mpu_violation_forced, fault_in_isr, fault_in_isr_unmapped) also build fixed/main.c, which must print DONE. These variants omit the faulting operation; they do not validate proposed diagnosis or repair advice.

Scoring a model's crash conclusions against expected.json is planned, not done. Nothing here measures model accuracy.

## Test

Needs arm-none-eabi-gcc, make, python3 and qemu-system-arm with the mps2-an386 machine.

    make test

This runs the unit tests, then builds every fixture, runs it in QEMU with a 10 s timeout, feeds the captured registers to the analyzer and compares the result with `expected.json`.

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
