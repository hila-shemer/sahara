// expect: 42
// memmove is correct in BOTH overlap directions
#include "libc.c"
i64 main() {
    u8 a[16];
    u64 i = 0;
    while (i < 16) { a[i] = (u8)(i + 1); i = i + 1; }
    memmove(a + 2, a, 10);            /* dst > src: backward copy */
    if (a[2] != 1) { return 1; }
    if (a[11] != 10) { return 2; }
    if (a[12] != 13) { return 3; }    /* past the window: untouched */
    u8 b[16];
    i = 0;
    while (i < 16) { b[i] = (u8)(i + 1); i = i + 1; }
    memmove(b, b + 3, 10);            /* dst < src: forward copy */
    if (b[0] != 4) { return 4; }
    if (b[9] != 13) { return 5; }
    if (b[10] != 11) { return 6; }
    if (memmove(b, b, 16) != b) { return 7; }   /* dst == src: no-op */
    if (b[0] != 4) { return 8; }
    return 42;
}
