// expect: 42
// oracle: no
// realloc corners per v0.2 B.3: (0,n) is malloc, (p,0) is free
// returning 0, grow moves with content intact (memcmp-verified),
// shrink stays in place and returns the tail to the free list.
#include "libc.c"
i64 main() {
    u8 *p = realloc((u8 *)0, 32);
    if (p == 0) { return 1; }
    u64 i = 0;
    while (i < 32) { p[i] = (u8)(i ^ 0x5A); i = i + 1; }
    u8 *snap = malloc(32);
    if (snap == 0) { return 2; }
    memcpy(snap, p, 32);
    u8 *q = realloc(p, 500);          /* grow: allocate-copy-free */
    if (q == 0) { return 3; }
    if (memcmp(q, snap, 32) != 0) { return 4; }
    q[499] = 0xAB;
    u8 *r = realloc(q, 16);           /* shrink: in place */
    if (r != q) { return 5; }
    if (memcmp(r, snap, 16) != 0) { return 6; }
    if (realloc(r, 0) != 0) { return 7; }   /* == free(r), returns 0 */
    free(snap);
    u8 *s = malloc(500);              /* the freed space is reusable */
    if (s == 0) { return 8; }
    free(s);
    return 42;
}
