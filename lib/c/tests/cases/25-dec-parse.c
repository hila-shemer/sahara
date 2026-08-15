// expect: 42
// oracle: no
// strict parsing: digits only, *end at the first non-digit, no-digits
// means end == s and 0, overflow wraps mod 2^64, end may be null
#include "libc.c"
i64 main() {
    u8 *s = "123abc";
    u8 *e = (u8 *)0;
    if (dec_to_u64(s, &e) != 123) { return 1; }
    if (e != s + 3) { return 2; }
    s = "abc";
    if (dec_to_u64(s, &e) != 0) { return 3; }
    if (e != s) { return 4; }
    if (dec_to_u64("42", (u8 **)0) != 42) { return 5; }
    s = "18446744073709551616";           /* 2^64 -> wraps to 0 */
    if (dec_to_u64(s, &e) != 0) { return 6; }
    if (e != s + 20) { return 7; }
    if (dec_to_u64("18446744073709551619", &e) != 3) { return 8; }
    if (dec_to_u64("007", &e) != 7) { return 9; }
    s = "-5";                             /* '-' is not a u64 digit */
    if (dec_to_u64(s, &e) != 0) { return 10; }
    if (e != s) { return 11; }
    s = "";
    if (dec_to_u64(s, &e) != 0) { return 12; }
    if (e != s) { return 13; }
    return 42;
}
