// expect: 42
// oracle: no
// parse(format(x)) == x over the corner table, all four widths and
// both bases; *end must land exactly on the written NUL
#include "libc.c"
i64 main() {
    u64 uvals[6];
    uvals[0] = 0; uvals[1] = 1; uvals[2] = 9; uvals[3] = 10;
    uvals[4] = 0xFFFFFFFFFFFFFFFF; uvals[5] = 12345678901234567890;
    u8 b[48];
    u8 *e;
    u64 i = 0;
    while (i < 6) {
        u64 n = u64_to_dec(b, uvals[i]);
        if (dec_to_u64(b, &e) != uvals[i]) { return 1; }
        if (e != b + n) { return 2; }
        n = u64_to_hex(b, uvals[i]);
        if (hex_to_u64(b, &e) != uvals[i]) { return 3; }
        if (e != b + n) { return 4; }
        i = i + 1;
    }
    i64 ivals[5];
    ivals[0] = 0; ivals[1] = -1; ivals[2] = 9223372036854775807;
    ivals[3] = (i64)0x8000000000000000; ivals[4] = -42;
    i = 0;
    while (i < 5) {
        u64 n = i64_to_dec(b, ivals[i]);
        if (dec_to_i64(b, &e) != ivals[i]) { return 5; }
        if (e != b + n) { return 6; }
        i = i + 1;
    }
    u128 xvals[5];
    xvals[0] = 0; xvals[1] = 1; xvals[2] = (u128)0 - 1;
    xvals[3] = (u128)1 << 64; xvals[4] = ((u128)1 << 100) + 5;
    i = 0;
    while (i < 5) {
        u64 n = u128_to_dec(b, xvals[i]);
        if (dec_to_u128(b, &e) != xvals[i]) { return 7; }
        if (e != b + n) { return 8; }
        n = u128_to_hex(b, xvals[i]);
        if (hex_to_u128(b, &e) != xvals[i]) { return 9; }
        if (e != b + n) { return 10; }
        i = i + 1;
    }
    return 42;
}
