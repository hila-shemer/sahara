// expect: 42
// oracle: no
// hex parsing takes either letter case (lowercase is an output-side
// rule), stops at the first non-hex byte, wraps mod 2^width
#include "libc.c"
i64 main() {
    u8 *s = "ff";
    u8 *e = (u8 *)0;
    if (hex_to_u64(s, &e) != 255) { return 1; }
    if (e != s + 2) { return 2; }
    if (hex_to_u64("DEADbeef", &e) != 0xdeadbeef) { return 3; }
    s = "12g4";
    if (hex_to_u64(s, &e) != 0x12) { return 4; }
    if (e != s + 2) { return 5; }
    s = "xyz";
    if (hex_to_u64(s, &e) != 0) { return 6; }
    if (e != s) { return 7; }
    /* 17 digits = 2^64: the u64 view wraps to 0 */
    if (hex_to_u64("10000000000000000", &e) != 0) { return 8; }
    /* ...but the u128 parser holds it */
    if (hex_to_u128("10000000000000000", &e) != ((u128)1 << 64)) { return 9; }
    /* 33 f's = 16^33 - 1, wraps mod 2^128 to all-ones */
    u128 ones = (u128)0 - 1;
    if (hex_to_u128("fffffffffffffffffffffffffffffffff", &e) != ones) { return 10; }
    return 42;
}
