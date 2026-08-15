// expect: 42
// oracle: no
// The bump-allocator killer (work-order risk 3): 100 x {malloc 1 MB;
// free} in a ~32 MB heap. A no-op free creeps to OOM by iteration 32;
// real reuse never returns 0. Touch only first/last byte - allocate
// big, touch little (the emu-py cycle budget).
#include "libc.c"
i64 main() {
    u64 i = 0;
    while (i < 100) {
        u8 *p = malloc(1048576);
        if (p == 0) { return 1; }
        p[0] = (u8)i;
        p[1048575] = (u8)(i + 1);
        if (p[0] != (i & 0xFF)) { return 2; }
        free(p);
        i = i + 1;
    }
    return 42;
}
