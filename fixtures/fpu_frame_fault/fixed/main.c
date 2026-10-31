#include "../../common/fixture.h"
int main(void)
{
    volatile float left = 1.25f, right = 2.5f;
    volatile float sum = left + right;
    (void)sum;
    fixture_done();
}
