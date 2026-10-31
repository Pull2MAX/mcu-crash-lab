# Cortex-M CFSR quick decode

CFSR (0xE000ED28) = MMFSR (bits 7:0) | BFSR (bits 15:8) | UFSR (bits 31:16)

## MMFSR (memory management)
- bit 0 IACCVIOL: instruction fetch from a no-execute or protected region
- bit 1 DACCVIOL: data access violation
- bit 3 MUNSTKERR: fault on unstacking at exception return
- bit 4 MSTKERR: fault on stacking at exception entry (often stack overflow)
- bit 7 MMARVALID: MMFAR holds the faulting address

## BFSR (bus)
- bit 8 IBUSERR: bus error on instruction fetch
- bit 9 PRECISERR: precise data bus error, BFAR holds the address
- bit 10 IMPRECISERR: imprecise data bus error (stacked PC may be after the real cause)
- bit 11 UNSTKERR / bit 12 STKERR: bus fault on unstack / stack
- bit 15 BFARVALID: BFAR holds the faulting address

## UFSR (usage)
- bit 16 UNDEFINSTR: undefined instruction
- bit 17 INVSTATE: invalid EPSR state, often calling a function pointer without the Thumb bit
- bit 18 INVPC: invalid exception return
- bit 19 NOCP: coprocessor access, often FPU not enabled
- bit 24 UNALIGNED: unaligned access trapped
- bit 25 DIVBYZERO: divide by zero trapped

## Notes
- HFSR bit 30 FORCED means a configurable fault escalated to HardFault; read CFSR for the real cause.
- IMPRECISERR: the stacked PC can be off; disable the write buffer (ACTLR.DISDEFWBUF) while debugging to make it precise.
