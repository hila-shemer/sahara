// expect: 7552
// oracle: no
// The no-address-randomization proof (v0.2 B.3 determinism): an
// alloc/free pattern returns a checksum of the OFFSETS it got (base-
// relative, so code-size drift can't move the expect). The pattern
// runs twice inside one process with a full free between - the second
// pass must reproduce the first exactly - and the harness's
// double-run compares the HALT lines across processes.
// Expected offsets (16-byte header, carve-from-front first-fit):
//   p1=16, p2=144, p3=368, free(p2), p4=144 (split of p2's hole),
//   p5=448 (hole too small), free(p1), p6=208 (whole 160-block, rem
//   16 < 32 so no split). cs = 16 + 2*144 + 3*368 + 5*144 + 7*448
//   + 11*208 = 7552.
#include "libc.c"
u64 pattern() {
    u8 *p1 = malloc(100);
    u64 base = __libc_heap_base;
    u8 *p2 = malloc(200);
    u8 *p3 = malloc(50);
    free(p2);
    u8 *p4 = malloc(40);
    u8 *p5 = malloc(300);
    free(p1);
    u8 *p6 = malloc(120);
    u64 cs = ((u64)p1 - base)
           + 2 * ((u64)p2 - base)
           + 3 * ((u64)p3 - base)
           + 5 * ((u64)p4 - base)
           + 7 * ((u64)p5 - base)
           + 11 * ((u64)p6 - base);
    free(p3);
    free(p4);
    free(p5);
    free(p6);
    return cs;
}
i64 main() {
    u64 a = pattern();
    u64 b = pattern();      /* pristine heap again: must reproduce */
    if (a != b) { return 1; }
    return (i64)a;
}
