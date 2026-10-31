#include <stdint.h>

__attribute__((noinline)) void write_unmapped(void)
{
    /* Zero is writable SSRAM; 0x60000000 is unmapped on QEMU MPS2 AN386. */
    volatile uint32_t *address = (volatile uint32_t *)0x60000000;
    *address = 42; /* FAULT HERE */
}

int main(void)
{
    write_unmapped();
    return 0;
}
