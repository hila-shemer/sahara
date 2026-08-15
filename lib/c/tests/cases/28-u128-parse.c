// expect: 42
// oracle: no
#include "libc.c"
i64 main() {
    u8 *s = "340282366920938463463374607431768211455";   /* 2^128-1 */
    u8 *e = (u8 *)0;
    u128 ones = (u128)0 - 1;
    if (dec_to_u128(s, &e) != ones) { return 1; }
    if (e != s + 39) { return 2; }
    s = "340282366920938463463374607431768211456";       /* 2^128 -> 0 */
    if (dec_to_u128(s, &e) != 0) { return 3; }
    if (e != s + 39) { return 4; }
    if (dec_to_u128("18446744073709551616", &e) != ((u128)1 << 64)) { return 5; }
    s = "";
    if (dec_to_u128(s, &e) != 0) { return 6; }
    if (e != s) { return 7; }
    return 42;
}
