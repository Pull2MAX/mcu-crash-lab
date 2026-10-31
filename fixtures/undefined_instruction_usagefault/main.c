__attribute__((noinline)) void undefined_instruction(void)
{
    __asm volatile ("udf #0"); /* FAULT HERE */
}

int main(void)
{
    undefined_instruction();
    return 0;
}
