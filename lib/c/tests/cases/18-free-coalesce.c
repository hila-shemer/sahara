// expect: 42
// oracle: no
// Coalescing with live neighbors around: middle freed alone, then
// left merges down, then right merges into the span. The final
// big == a assert pins the REFERENCE internals (address-ordered
// first-fit, carve from the front) - the contract only demands the
// merge, but determinism makes the stronger check stable; re-bless it
// if the internals legitimately change.
#include "libc.c"
i64 main() {
    u8 *a = malloc(4096);
    u8 *b = malloc(4096);
    u8 *c = malloc(4096);
    u8 *guard = malloc(16);
    if (a == 0 || b == 0 || c == 0 || guard == 0) { return 1; }
    guard[0] = 0x77;
    free(b);
    free(a);
    free(c);
    /* 3 x (16 + 4096) merged = 12336; payload 12320 needs the merge */
    u8 *big = malloc(12320);
    if (big == 0) { return 2; }
    if (big != a) { return 3; }
    big[0] = 1;
    big[12319] = 2;
    if (guard[0] != 0x77) { return 4; }
    free(big);
    free(guard);
    return 42;
}
