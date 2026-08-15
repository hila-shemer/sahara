// expect: 42
// oracle: no
// the pinned corners of v0.2 B.3: malloc(0) -> 0, free(0) no-op, and
// absurd sizes fail with 0 - never a trap, never a wrap
#include "libc.c"
i64 main() {
    if (malloc(0) != 0) { return 1; }
    free((u8 *)0);
    u8 *p = malloc(24);
    if (p == 0) { return 2; }
    free(p);
    free((u8 *)0);
    if (malloc(0xFFFFFFFFFFFFFFFF) != 0) { return 3; }  /* n+15 would wrap */
    if (malloc(0x7FFFFFFFFFFFFFFF) != 0) { return 4; }
    if (malloc(0x02000000) != 0) { return 5; }          /* > whole arena */
    return 42;
}
