---
name: mcu-crash-lab
description: Analyze Cortex-M crashes (HardFault, MemManage, BusFault, UsageFault) from fault registers and the firmware image (GCC .elf, Keil .axf, IAR .out, plus the .map). Use when the user pastes CFSR/HFSR/PC/LR values or a crash dump, or says a Cortex-M board hard-faults or resets.
---

# MCU crash lab

Read the fault registers, find the faulting line, say what went wrong, and say whether it was reproduced in an emulator.

## You need
- CFSR, HFSR, and MMFAR/BFAR if their valid bits are set
- stacked PC and LR
- the image from the build that crashed (`.elf`, `.axf` or `.out`), and the `.map` if there is one

No image means no decoding. Ask for it; don't guess function names. If the user can't confirm the image matches the flashed binary, say the line numbers may be off.

## Steps
1. **Decode CFSR/HFSR.** Name each set bit (see `references/cortex-m-cfsr.md`). Check MMARVALID and BFARVALID before trusting MMFAR/BFAR. HFSR FORCED means a configurable fault was escalated.
2. **Find the code.** Put the registers in a text file as `R0=0x..`, `PC=0x..`, `CFSR=0x..` lines and run `python3 scripts/analyze_crash.py dump.txt --elf <image>` (add `--json` for machine output). It decodes the fault bits and symbolizes PC and LR. To do it by hand: `arm-none-eabi-addr2line -pfiaC -e <image> <pc> <lr>`. Keil `.axf` and IAR `.out` are ELF, so this normally works. If it prints `??:0`, find the nearest symbol at or below the PC in the `.map` and report function plus offset. Clear bit 0 of LR first, and don't look up EXC_RETURN values (`0xFFFFFFF1/9/D`).
3. **Classify.** Null/wild pointer, stack overflow, divide by zero, unaligned access, bad function pointer or Thumb state, peripheral bus error, or a fault inside an ISR (stacked xPSR low 9 bits is the exception number). Quote the bits and address that support it.
4. **Reproduce if you can.** If `fixtures/` has a matching case and QEMU or Renode is installed, run it and compare registers. Label the result:
   - Reproduced: same CFSR bits in the emulator
   - Static analysis only: not run in an emulator (always the case for watchdog resets and use-after-free)
   - Not reproduced: the emulator gave different bits
   Report only the counts the test suite printed.
5. **Report.** Fault class and bits, function and line, most likely cause, other candidates with how to rule them out, one concrete fix, and the status from step 4.

## Gotchas
- Imprecise bus faults (IMPRECISERR) can be reported after the instruction that caused them, so the PC may point past the real culprit.
- DIVBYZERO and UNALIGNED only fault when `CCR.DIV_0_TRP` / `CCR.UNALIGN_TRP` are set.
- ESP32 and Zephyr logs: see `references/esp32-panic.md` and `references/zephyr-fatal.md`.
