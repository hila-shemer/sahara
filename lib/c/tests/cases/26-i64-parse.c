// expect: 42
// oracle: no
// one optional leading '-', and a bare '-' consumes NOTHING (end
// back at s, not past the sign); MIN parses via the u64 wrap
#include "libc.c"
i64 main() {
    u8 *s = "-42xyz";
    u8 *e = (u8 *)0;
    if (dec_to_i64(s, &e) != -42) { return 1; }
    if (e != s + 3) { return 2; }
    s = "17";
    if (dec_to_i64(s, &e) != 17) { return 3; }
    if (e != s + 2) { return 4; }
    s = "-";
    if (dec_to_i64(s, &e) != 0) { return 5; }
    if (e != s) { return 6; }
    s = "--3";
    if (dec_to_i64(s, &e) != 0) { return 7; }
    if (e != s) { return 8; }
    i64 min = (i64)0x8000000000000000;
    if (dec_to_i64("-9223372036854775808", &e) != min) { return 9; }
    if (dec_to_i64("9223372036854775807", &e) != 9223372036854775807) { return 10; }
    /* MAX+2 wraps mod 2^64, then reads back as i64: MIN+1 */
    if (dec_to_i64("9223372036854775809", &e) != min + 1) { return 11; }
    return 42;
}
