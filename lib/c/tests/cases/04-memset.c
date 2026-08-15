// expect: 42
// memset fills exactly [dst, dst+n) with c mod 256
#include "libc.c"
i64 main() {
    u8 a[24];
    u64 i = 0;
    while (i < 24) { a[i] = 7; i = i + 1; }
    u8 *r = memset(a + 4, 0x141, 16);   /* c mod 256 = 0x41 */
    if (r != a + 4) { return 1; }
    if (a[3] != 7) { return 2; }
    if (a[4] != 0x41) { return 3; }
    if (a[19] != 0x41) { return 4; }
    if (a[20] != 7) { return 5; }
    memset(a, 0, 4);
    if (a[0] != 0) { return 6; }
    if (a[4] != 0x41) { return 7; }
    return 42;
}
