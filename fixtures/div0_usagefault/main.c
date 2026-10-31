#include <stdint.h>

#define SCB_CCR (*(volatile uint32_t *)0xE000ED14)

__attribute__((noinline)) int divide_by_zero(void)
{
    volatile int divisor = 0;
    int dividend = 42;
    int quotient;
    __asm volatile ("sdiv %0, %1, %2" : "=r" (quotient) : "r" (dividend), "r" (divisor)); /* FAULT HERE */
    return quotient;
}

int main(void)
{
    SCB_CCR |= 1u << 4; /* DIV_0_TRP */
    __asm volatile ("dsb\nisb" ::: "memory");
    return divide_by_zero();
}
