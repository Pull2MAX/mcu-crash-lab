#include "../common/systick.h"

void SysTick_Handler(void)
{
    /* SysTick and BusFault both have priority 0; BusFault cannot preempt,
       so it escalates to HardFault with HFSR.FORCED. */
    *(volatile uint32_t *)0x60000000 = 42; /* FAULT HERE */
}

int main(void)
{
    start_systick();
    for (;;) {}
}
