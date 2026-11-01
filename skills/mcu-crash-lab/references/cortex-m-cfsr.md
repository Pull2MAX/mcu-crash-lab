# Cortex-M CFSR quick decode

CFSR (0xE000ED28) = MMFSR (bits 7:0) | BFSR (bits 15:8) | UFSR (bits 31:16)

## MMFSR (memory management)
- bit 0 IACCVIOL: instruction fetch from a no-execute or protected region (does not set MMFAR or MMARVALID)
- bit 1 DACCVIOL: data access violation
- bit 3 MUNSTKERR: fault on unstacking at exception return
- bit 4 MSTKERR: fault on stacking at exception entry (often stack overflow)
- bit 5 MLSPERR: fault during lazy FP state preservation
- bit 7 MMARVALID: MMFAR holds the faulting address

## BFSR (bus)
- bit 8 IBUSERR: bus error on instruction fetch
- bit 9 PRECISERR: precise data bus error; BFAR holds the address only if BFARVALID is set
- bit 10 IMPRECISERR: imprecise data bus error (stacked PC may be after the real cause)
- bit 11 UNSTKERR / bit 12 STKERR: bus fault on unstack / stack
- bit 13 LSPERR: bus fault during lazy FP state preservation
- bit 15 BFARVALID: BFAR holds the faulting address

## UFSR (usage)
- bit 16 UNDEFINSTR: undefined instruction
- bit 17 INVSTATE: invalid EPSR state, often calling a function pointer without the Thumb bit
- bit 18 INVPC: invalid exception return
- bit 19 NOCP: coprocessor access, often FPU not enabled
- bit 24 UNALIGNED: unaligned access trapped
- bit 20 STKOF: stack limit overflow (ARMv8-M only)
- bit 25 DIVBYZERO: divide by zero trapped

## Notes
- CFSR and HFSR are sticky; write 1 to clear. Bits from an earlier recovered fault stay set, so a stale FORCED or CFSR bit can be mistaken for the current fault.
- HFSR bit 30 FORCED: a configurable fault escalated to HardFault. CFSR usually has the cause, but an SVC or BKPT that cannot be taken at the current priority (inside a higher-priority handler, or masked by BASEPRI/PRIMASK) escalates with CFSR zero.
- MMFAR and BFAR may share one physical register on ARMv7-M. Then at most one VALID bit is set, and the other register reads as unknown.
- IMPRECISERR: the stacked PC can be after the store. On Cortex-M3/M4, ACTLR.DISDEFWBUF (disable the write buffer) makes it precise while debugging; Cortex-M7 has no such bit.
- A fault raised inside an ISR of the same or higher priority cannot preempt it, so it escalates to HardFault with FORCED set. Read CFSR for the cause. Stacked xPSR bits 8:0 are the exception number; for an external interrupt IRQn = exception number - 16.
- Stacked PC is at SP+0x18 in the basic frame (0x20 bytes) and in the FPU extended frame (0x68 bytes) on ARMv7-M. EXC_RETURN bit 4 clear means the extended frame. ARMv8-M with TrustZone can add a state context, and FPCCR.TS=1 makes the extended frame larger.
- EXC_RETURN values: 0xFFFFFFF1 (handler, MSP), 0xFFFFFFF9 (thread, MSP), 0xFFFFFFFD (thread, PSP); with an extended frame 0xFFFFFFE1, 0xFFFFFFE9, 0xFFFFFFED. ARMv8-M uses other values.
- With MUNSTKERR/UNSTKERR no new frame was pushed: the frame at SP is the earlier one, and its PC is the interrupted code.
- Lazy stacking: the FP registers are saved only when FPCCR.LSPACT is set and a handler runs an FP instruction. Read FPCCR before any FP instruction in the handler, or LSPACT is already cleared.
