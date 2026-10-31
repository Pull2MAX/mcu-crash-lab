#include <stdint.h>

__attribute__((noinline)) void write_unmapped(void)
{
    *(volatile uint32_t *)0x60000000 = 42; /* FAULT HERE */
}

int main(void)
{
    volatile float left = 1.25f, right = 2.5f;
    volatile float sum = left + right;
    (void)sum;
    write_unmapped();
    return 0;
}
