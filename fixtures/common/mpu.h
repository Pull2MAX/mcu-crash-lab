#include "fixture.h"

static inline void configure_buffer_mpu(volatile uint32_t *buffer, uint32_t access)
{
    *(volatile uint32_t *)0xE000ED98 = 0;
    *(volatile uint32_t *)0xE000ED9C = (uint32_t)buffer;
    *(volatile uint32_t *)0xE000EDA0 = (access << 24) | (4u << 1) | 1;
    *(volatile uint32_t *)0xE000ED94 = 5; /* ENABLE | PRIVDEFENA; region is 32 bytes. */
    __asm volatile ("dsb\nisb" ::: "memory");
}
