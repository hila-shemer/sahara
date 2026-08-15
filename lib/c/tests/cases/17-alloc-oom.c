// expect: 42
// oracle: no
// OOM at the ceiling: malloc 1 MB blocks until 0, assert the failure
// IS 0 (the trace gates catch any trap), the count matches the arena
// arithmetic exactly, then free everything and take the arena in ONE
// allocation - only full coalescing can satisfy it.
#include "libc.c"
i64 main() {
    u64 ptrs[40];
    u64 count = 0;
    while (count < 40) {
        u8 *p = malloc(1048576);
        if (p == 0) { break; }
        p[0] = 1;                    /* touch little */
        ptrs[count] = (u64)p;
        count = count + 1;
    }
    if (count == 40) { return 1; }   /* never hit the ceiling: wrong */
    u64 need = 1048576 + 16;
    u64 avail = __libc_heap_end - __libc_heap_base;
    if (count != avail / need) { return 2; }
    if (malloc(1048576) != 0) { return 3; }   /* still OOM, still 0 */
    /* free evens then odds: every merge shape (right neighbor, left
     * neighbor, both) occurs on the odd pass */
    u64 i = 0;
    while (i < count) { free((u8 *)ptrs[i]); i = i + 2; }
    i = 1;
    while (i < count) { free((u8 *)ptrs[i]); i = i + 2; }
    u8 *big = malloc(avail - 16);
    if (big == 0) { return 4; }
    big[0] = 7;
    big[avail - 17] = 9;
    if (big[0] != 7) { return 5; }
    if (big[avail - 17] != 9) { return 6; }
    free(big);
    return 42;
}
