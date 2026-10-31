# mcu-crash-lab

An agent skill for triaging Cortex-M crashes. Give it CFSR/HFSR, the fault address registers, stacked PC/LR and the matching ELF; it names the fault bits and the faulting source line. Each fixture here is a small firmware that crashes on purpose, so the analyzer can be checked against a real fault instead of a hand-written dump.

## Use

Copy `skills/mcu-crash-lab/` to wherever your agent loads skills from. Install locations differ between agents; check your agent's docs.

Run the analyzer on a dump:

    python3 skills/mcu-crash-lab/scripts/analyze_crash.py fixtures/div0_usagefault/dump.txt --elf path/to/firmware.elf --json

It needs `arm-none-eabi-addr2line` on PATH.

## Fixtures

3 verified scenarios (from the last `make test`, see `tests/results.json`).

| Fixture | Fault | Status |
|---|---|---|
| unmapped_write_busfault | precise BusFault (PRECISERR, BFARVALID) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| div0_usagefault | UsageFault (DIVBYZERO, CCR.DIV_0_TRP set) | verified in qemu-system-arm 10.0.13 (mps2-an386) |
| undefined_instruction_usagefault | UsageFault (UNDEFINSTR) | verified in qemu-system-arm 10.0.13 (mps2-an386) |

The BusFault fixture writes to 0x60000000, not to NULL. On the MPS2 AN386 model address 0 is RAM, so a NULL write does not fault there. On real parts where 0 is flash or unmapped, a NULL write gives the same PRECISERR/BFARVALID pattern, but that is not what this fixture tests.

Each fixture has `expected.json` with the faulting function, line (marked `/* FAULT HERE */` in main.c) and CFSR bits. `dump.txt` is the dump captured from the QEMU run, used by the unit tests and as the input when QEMU is missing. Without QEMU the runner reports "static analysis only" and counts zero verified scenarios.

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
