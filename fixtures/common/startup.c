#include <stdint.h>

#define SCB_SHCSR (*(volatile uint32_t *)0xE000ED24)
#define SCB_CFSR  (*(volatile uint32_t *)0xE000ED28)
#define SCB_HFSR  (*(volatile uint32_t *)0xE000ED2C)
#define SCB_MMFAR (*(volatile uint32_t *)0xE000ED34)
#define SCB_BFAR  (*(volatile uint32_t *)0xE000ED38)

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
int main(void);

static void semihost_write(const char *text)
{
    register uint32_t operation __asm("r0") = 4; /* SYS_WRITE0 */
    register const char *argument __asm("r1") = text;
    __asm volatile ("bkpt #0xab" : "+r" (operation) : "r" (argument) : "memory");
}

__attribute__((noreturn)) static void exit_qemu(uint32_t reason)
{
    register uint32_t operation __asm("r0") = 0x18; /* SYS_EXIT */
    register uint32_t argument __asm("r1") = reason;
    __asm volatile ("bkpt #0xab" : "+r" (operation) : "r" (argument) : "memory");
    for (;;) {}
}

static void dump_value(const char *name, uint32_t value)
{
    char text[12] = "0x00000000\n";
    const char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < 8; i++)
        text[2 + i] = digits[(value >> (28 - 4 * i)) & 15];
    semihost_write(name);
    semihost_write("=");
    semihost_write(text);
}

__attribute__((noreturn)) void fault_dump(uint32_t *frame, uint32_t exc_return)
{
    static const char *const names[] = {"R0", "R1", "R2", "R3", "R12", "LR", "PC", "xPSR"};
    for (unsigned i = 0; i < 8; i++)
        dump_value(names[i], frame[i]);
    dump_value("EXC_RETURN", exc_return);
    dump_value("SP", (uint32_t)frame); /* Base of the hardware frame on MSP or PSP. */
    dump_value("CFSR", SCB_CFSR);
    dump_value("HFSR", SCB_HFSR);
    dump_value("MMFAR", SCB_MMFAR);
    dump_value("BFAR", SCB_BFAR);
    exit_qemu(0x20026); /* ADP_Stopped_ApplicationExit */
}

__attribute__((naked)) void Fault_Handler(void)
{
    __asm volatile (
        "tst lr, #4\n"
        "ite eq\n"
        "mrseq r0, msp\n"
        "mrsne r0, psp\n"
        "mov r1, lr\n"
        "b fault_dump\n");
}

static void Default_Handler(void)
{
    exit_qemu(0x20023);
}

void Reset_Handler(void)
{
    uint32_t *source = &_sidata;
    for (uint32_t *dest = &_sdata; dest < &_edata;)
        *dest++ = *source++;
    for (uint32_t *dest = &_sbss; dest < &_ebss;)
        *dest++ = 0;
    SCB_SHCSR |= 7u << 16; /* MemManage, BusFault, UsageFault handlers enabled. */
    __asm volatile ("dsb\nisb" ::: "memory");
    main();
    exit_qemu(0x20023);
}

__attribute__((section(".isr_vector"), used))
const void *const vectors[16] = {
    &_estack, Reset_Handler, Default_Handler, Fault_Handler,
    Fault_Handler, Fault_Handler, Fault_Handler, 0, 0, 0, 0,
    Default_Handler, Default_Handler, 0, Default_Handler, Default_Handler,
};
