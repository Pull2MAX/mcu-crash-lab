#include "../common/mpu.h"

volatile uint32_t buffer[8] __attribute__((aligned(32)));

__attribute__((noinline)) void write_buffer(void)
{
    buffer[0] = 42; /* FAULT HERE */
}

int main(void)
{
    SCB_SHCSR |= 1u << 16;
    configure_buffer_mpu(buffer, 6); /* AP: read-only. */
    write_buffer();
    return 0;
}
