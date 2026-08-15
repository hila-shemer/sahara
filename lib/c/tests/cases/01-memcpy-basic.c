// expect: 42
// memcpy copies, returns dst, and 0xFF bytes survive the u8 loops
#include "libc.c"
i64 main() {
    u8 a[32];
    u8 b[32];
    u64 i = 0;
    while (i < 32) { a[i] = (u8)(i * 7 + 3); b[i] = 0; i = i + 1; }
    a[5] = 0xFF;
    a[6] = 0x00;
    u8 *r = memcpy(b, a, 32);
    if (r != b) { return 1; }
    if (memcmp(a, b, 32) != 0) { return 2; }
    if (b[5] != 0xFF) { return 3; }
    if (b[6] != 0) { return 4; }
    return 42;
}
