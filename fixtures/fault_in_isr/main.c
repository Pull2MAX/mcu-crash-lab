#include "../common/systick.h"

static volatile uint32_t finished;

void SysTick_Handler(void)
{
    /* Address 0 is writable SSRAM on QEMU MPS2 AN386, so this store does not fault. */
    *(volatile uint32_t *)0 = 42; /* FAULT HERE */
    SYSTICK_CTRL = 0;
    finished = 1;
}

int main(void)
{
    start_systick();
    while (!finished) {}
    dump_value("CFSR", SCB_CFSR);
    dump_value("HFSR", SCB_HFSR);
    dump_value("MMFAR", SCB_MMFAR);
    dump_value("BFAR", SCB_BFAR);
    fixture_done();
}
