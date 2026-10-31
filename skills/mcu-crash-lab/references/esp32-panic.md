# ESP32 panic and reset quick decode

## Decode first
- `idf.py monitor` decodes backtraces automatically if run from the project that built the flashed firmware.
- Manual: `xtensa-esp32-elf-addr2line -pfiaC -e build/<app>.elf 0x400d1234:0x3ffb1234 ...` (use `xtensa-esp32s3-elf-` for S3, `riscv32-esp-elf-` for C3/C6/H2).
- Only the `0x400...` style PC values (code addresses) are meaningful for addr2line; the second value in each pair is the stack pointer.
- ELF must match the flashed build exactly.

## Common panic messages
- `LoadProhibited` / `StoreProhibited` (Xtensa) or `Load access fault` / `Store/AMO access fault` (RISC-V): invalid memory access. `EXCVADDR` (Xtensa) or `MTVAL` (RISC-V) is the address; near 0 means null pointer.
- `InstrFetchProhibited`: jumped to a bad address, often a corrupted function pointer or stack smash.
- `IntegerDivideByZero`: divide by zero.
- `Unaligned`: unaligned access to memory that requires alignment.
- `Stack canary watchpoint triggered (taskname)`: stack overflow in that task. Increase stack size or reduce locals; enable `CONFIG_FREERTOS_CHECK_STACKOVERFLOW`.
- `Task watchdog got triggered`: a task did not yield; the log lists which tasks and CPU cores.
- `Interrupt wdt timeout on CPU0/1`: interrupts disabled too long or ISR running too long.
- `Cache disabled but cached memory region accessed`: ISR marked IRAM_ATTR touched flash code or data (or a non-IRAM function was called from it during flash operations).
- `CORRUPT HEAP`: heap metadata overwritten; enable heap poisoning (`CONFIG_HEAP_POISONING_COMPREHENSIVE`) to find the writer.
- `Brownout detector was triggered`: supply voltage dipped, check power and decoupling before debugging code.
- `abort() was called at PC ...`: an assert or explicit abort; the line above the backtrace names the failed assertion.

## Reset reasons on boot (`rst:0x..`)
- `POWERON_RESET`: normal power-up.
- `SW_CPU_RESET`: software restart or panic reset.
- `TG0WDT_SYS_RESET` / `RTCWDT_RTC_RESET`: watchdog reset. Repeated early RTCWDT resets often point to wrong flash mode or frequency, or strapping pin problems.
- `DEEPSLEEP_RESET`: wake from deep sleep.

## Boot loop checklist
1. Flash mode and speed match the module (QIO/DIO, 40/80 MHz).
2. Partition table fits the flash size and the app is not larger than its partition.
3. Strapping pins (e.g. GPIO0, GPIO2, GPIO12, GPIO15 on classic ESP32) are not driven at boot by external circuitry.
4. Power supply holds 3.3 V during Wi-Fi bursts.
