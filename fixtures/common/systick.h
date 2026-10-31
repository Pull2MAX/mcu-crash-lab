#include "fixture.h"

#define SYSTICK_CTRL (*(volatile uint32_t *)0xE000E010)

static inline void start_systick(void)
{
    *(volatile uint32_t *)0xE000E014 = 999;
    *(volatile uint32_t *)0xE000E018 = 0;
    SYSTICK_CTRL = 7;
}
