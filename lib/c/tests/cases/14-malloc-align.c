// expect: 42
// oracle: no
// every malloc result is 16-aligned across mixed sizes (the LD128
// granule - a misaligned result would also trip the UNALIGNED gate)
#include "libc.c"
i64 main() {
    u64 sizes[8];
    sizes[0] = 1; sizes[1] = 2; sizes[2] = 15; sizes[3] = 16;
    sizes[4] = 17; sizes[5] = 100; sizes[6] = 4096; sizes[7] = 65521;
    u8 *ptrs[8];
    u64 i = 0;
    while (i < 8) {
        u8 *p = malloc(sizes[i]);
        if (p == 0) { return 1; }
        if (((u64)p & 15) != 0) { return 2; }
        p[0] = (u8)i;
        p[sizes[i] - 1] = (u8)(i + 100);
        ptrs[i] = p;
        i = i + 1;
    }
    i = 0;
    while (i < 8) {
        /* size-1 blocks: first byte IS the last byte, last write wins */
        if (sizes[i] > 1) {
            if (ptrs[i][0] != i) { return 3; }
        }
        if (ptrs[i][sizes[i] - 1] != i + 100) { return 4; }
        i = i + 1;
    }
    i = 1;
    while (i < 8) {
        if (!(ptrs[i - 1] < ptrs[i])) { return 5; }
        i = i + 1;
    }
    i = 0;
    while (i < 8) { free(ptrs[i]); i = i + 1; }
    return 42;
}
