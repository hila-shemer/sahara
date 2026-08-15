// expect: 42
// 0xFF-heavy corners for memcmp, clamped to signs so the host memcmp
// agrees exactly (work-order risk 1: the canonical-form byte-loop trap)
#include "libc.c"
i64 sgn(i64 x) { if (x < 0) { return -1; } if (x > 0) { return 1; } return 0; }
i64 main() {
    u8 a[8];
    u8 b[8];
    u64 i = 0;
    while (i < 8) { a[i] = 0xFF; b[i] = 0xFF; i = i + 1; }
    if (sgn(memcmp(a, b, 8)) != 0) { return 1; }
    b[7] = 0x00;
    if (sgn(memcmp(a, b, 8)) != 1) { return 2; }
    if (sgn(memcmp(b, a, 8)) != -1) { return 3; }
    a[0] = 0x00; a[1] = 0x01;
    b[0] = 0x00; b[1] = 0x02; b[7] = 0xFF;
    if (sgn(memcmp(a, b, 8)) != -1) { return 4; }
    if (sgn(memcmp(a, b, 1)) != 0) { return 5; }
    return 42;
}
