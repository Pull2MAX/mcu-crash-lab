# Offline demo

Run `make demo` at the repository root with Python 3 and
`arm-none-eabi-addr2line` on PATH. No compiler or QEMU is needed.

`firmware.elf` is built from `fixtures/unmapped_write_busfault` with Arm GNU
Toolchain 14.3.Rel1, using that fixture's Makefile. It retains debug information.
Rebuild with `make -C fixtures/unmapped_write_busfault` and copy
`fixtures/unmapped_write_busfault/build/firmware.elf` here.

`crash_full.txt` is a QEMU 10.0.13 capture on mps2-an386: a write to unmapped
address 0x60000000 sets PRECISERR and BFARVALID. The store is at PC 0x50.

`crash_thin.txt` is hand-built from that capture. CFSR contains only
IMPRECISERR, BFAR is absent, and PC is 0x52, the instruction after the store.
It demonstrates uncertainty about the faulting instruction, not a QEMU
reproduction of IMPRECISERR. Neither example adds a verified scenario.
