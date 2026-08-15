// expect: 42
// oracle: no
// The raw difference convention: (i64)a[i] - (i64)b[i] at the first
// differing byte - stronger than C's sign-only contract (v0.2 B.2),
// so the host has no opinion on the exact values.
#include "libc.c"
i64 main() {
    u8 a[4];
    u8 b[4];
    a[0] = 0x10; a[1] = 0xFF; a[2] = 3; a[3] = 9;
    b[0] = 0x10; b[1] = 0x01; b[2] = 3; b[3] = 200;
    if (memcmp(a, b, 4) != 254) { return 1; }
    if (memcmp(b, a, 4) != -254) { return 2; }
    if (memcmp(a, b, 1) != 0) { return 3; }
    if (memcmp(a + 3, b + 3, 1) != 9 - 200) { return 4; }
    return 42;
}
