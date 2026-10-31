# Zephyr fatal error quick decode

## Typical output
```
E: ***** BUS FAULT *****
E:   Precise data bus error
E:   BFAR Address: 0x4
E: r0/a1:  ... pc: 0x...  lr: 0x...
E: Faulting instruction address (r15/pc): 0x...
E: >>> ZEPHYR FATAL ERROR 0: CPU exception on CPU 0
E: Current thread: 0x... (name)
```

## Decode
- Resolve the faulting PC and LR with the build's ELF: `arm-none-eabi-addr2line -pfiaC -e build/zephyr/zephyr.elf <pc> <lr>` (or the toolchain prefix for your architecture).
- `Current thread` tells you which thread or ISR context faulted.
- Fault names map to the same Cortex-M causes as CFSR; see cortex-m-cfsr.md.

## Common fatal reasons
- `K_ERR_CPU_EXCEPTION` (0): CPU fault, decode as above.
- `K_ERR_SPURIOUS_IRQ`: interrupt with no handler registered.
- `K_ERR_STACK_CHK_FAIL`: stack overflow detected by the stack canary.
- `K_ERR_KERNEL_OOPS` / `K_ERR_KERNEL_PANIC`: assertion or `k_oops()` / `k_panic()` call.

## Debugging aids (Kconfig)
- `CONFIG_THREAD_ANALYZER=y` with `CONFIG_THREAD_NAME=y`: report per-thread stack usage.
- `CONFIG_STACK_SENTINEL=y` or `CONFIG_HW_STACK_PROTECTION=y`: catch overflows earlier.
- `CONFIG_ASSERT=y`: enable `__ASSERT` checks.
- `CONFIG_DEBUG_OPTIMIZATIONS=y`: easier-to-read backtraces.
- `west debug` or `west attach` to inspect the live fault.
