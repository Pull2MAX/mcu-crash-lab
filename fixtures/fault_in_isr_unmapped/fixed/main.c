#include "../../common/systick.h"
static volatile uint32_t value, finished;
void SysTick_Handler(void) { value = 42; SYSTICK_CTRL = 0; finished = 1; }
int main(void)
{
    start_systick();
    while (!finished) {}
    fixture_done();
}
