#include "../../common/mpu.h"
volatile uint32_t buffer[8] __attribute__((aligned(32)));
int main(void)
{
    configure_buffer_mpu(buffer, 3); /* AP: read/write. */
    buffer[0] = 42;
    fixture_done();
}
