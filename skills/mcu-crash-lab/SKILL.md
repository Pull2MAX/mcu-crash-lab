---
name: mcu-crash-lab
description: Analyze Cortex-M crashes (HardFault, MemManage, BusFault, UsageFault) from fault registers and the firmware image (GCC .elf, Keil .axf, IAR .out, plus the .map). Use when the user pastes CFSR/HFSR/PC/LR values or a crash dump, or says a Cortex-M board hard-faults or resets.
---

# MCU crash lab

Read the fault registers, find the faulting line, say what went wrong, and say how much of it was checked.

Covers ARMv7-M and ARMv8-M Mainline (Cortex-M3/M4/M7/M33). Cortex-M0/M0+ (ARMv6-M) has no CFSR, HFSR, MMFAR or BFAR: all you get is the stacked frame, so decode PC and LR and treat everything else as Speculative.

## You need
- CFSR, HFSR, and MMFAR/BFAR if their valid bits are set
- stacked R0-R3, R12, LR, PC and xPSR, the EXC_RETURN value the handler was entered with, and SP
- FPCCR, if the firmware uses the FPU and it was read before any FP instruction in the handler
- the image from the build that crashed (`.elf`, `.axf` or `.out`), and the `.map` if there is one

No image means no decoding. Ask for it; don't guess function names. If the user can't confirm the image matches the flashed binary, say the line numbers may be off.

## Steps
1. **Decode CFSR/HFSR.** Name each set bit (see `references/cortex-m-cfsr.md`). CFSR and HFSR are sticky: bits left over from an earlier, recovered fault look the same as new ones, so ask whether they were cleared. Check MMARVALID and BFARVALID before trusting MMFAR/BFAR.
2. **Find the code.** Put the registers in a text file, one `NAME=0x..` per line with the `0x` prefix (`R0`, `PC`, `LR`, `xPSR`, `EXC_RETURN`, `SP`, `CFSR`, ...), and run `python3 scripts/analyze_crash.py dump.txt --elf <image>` (add `--json` for machine output). It decodes the fault bits, symbolizes PC and LR, and lists `caveats` (facts that weaken the reading, such as an imprecise fault); carry them into the report. By hand: `arm-none-eabi-addr2line -pfiaC -e <image> <pc> <lr>`, with LR minus 2 (clear bit 0 first) so it points at the call, not the instruction after it. Keil `.axf` and IAR `.out` are ELF, so this normally works. If it prints `??:0`, find the nearest symbol at or below the PC in the `.map` and report function plus offset. Never look up EXC_RETURN values (`0xFFFFFFE1/E9/ED/F1/F9/FD`).
3. **Classify.** Null/wild pointer, stack overflow, divide by zero, unaligned access, bad function pointer or Thumb state, peripheral bus error, or a fault inside an ISR (stacked xPSR low 9 bits is the exception number). Quote the bits and address that support it. If PC points at a load or store, `arm-none-eabi-objdump -d` around it shows the base register; compare it with the stacked R0-R3 and R12.
4. **Check against an emulator, if one is there.** `fixtures/` holds small synthetic programs, not the user's firmware. Running one shows that this kind of fault produces these bits in QEMU; it does not reproduce the user's crash. Write it that way:
   - Reproduced on the user's firmware: only if you ran their image in an emulator and got the same PC and CFSR
   - Same fault class seen in a fixture: a matching fixture gave the same bits; say which and that QEMU is not silicon (it has no write buffer, so it reports a store to an unmapped address as precise where real M3/M4 usually report IMPRECISERR)
   - Static analysis only: nothing was run (always the case for watchdog resets and use-after-free)
   Say which of these applies. Don't quote test-suite counts to the user.
5. **Report.** Fault class and bits, function and line, the cause, one concrete fix, and the status from step 4. Tag each cause:
   - Confirmed: the registers or a rerun show it
   - Likely: fits the evidence, nothing contradicts it
   - Speculative: fits, but other causes fit equally well
   - Undetermined: the evidence is not enough to pick; say so
   Never write Confirmed for a cause you only inferred. For each candidate cause write the evidence for it, any fact that conflicts with it, what extra material would tell it apart from the others (a second dump, the map, the code around PC), and what would make you drop it.
   After the user applies the fix and reruns, check the fault is gone; until then the fix is a suggestion.

## Gotchas
- IMPRECISERR: the bus fault is reported after the store that caused it, so PC may point past the real culprit and BFAR is not valid.
- STKERR/MSTKERR: the exception frame may be incomplete, so stacked PC and LR can be wrong or missing. UNSTKERR/MUNSTKERR: no new frame was pushed; the frame at SP is the older one and its PC is the interrupted code, not the faulting instruction.
- HFSR.FORCED means an escalation happened. CFSR usually names the cause, but it can be zero: an SVC or BKPT that cannot be taken at the current priority escalates with no CFSR bit.
- DIVBYZERO only faults when `CCR.DIV_0_TRP` is set. On ARMv7-M, unaligned LDR/STR also needs `CCR.UNALIGN_TRP`, but unaligned LDM, STM, LDRD, STRD and the exclusive loads and stores always fault.
- INVSTATE: the stacked PC is the bad branch target. Look at LR and the caller for the real bug.
- The stacked PC is 0x18 bytes into the frame on ARMv7-M. Do not assume this for ARMv8-M with TrustZone, which may add a state context.
- An extended (FPU) frame being allocated does not mean the FP registers were saved: with lazy stacking, FPCCR.LSPACT says whether they are still pending. Read FPCCR before the handler runs any FP instruction, or LSPACT is already cleared.
- A matching function name does not prove the image is the one that crashed. Compare the build ID (`readelf -n`) with the flashed binary when you can.
- ESP32 and Zephyr logs: see `references/esp32-panic.md` and `references/zephyr-fatal.md`.
