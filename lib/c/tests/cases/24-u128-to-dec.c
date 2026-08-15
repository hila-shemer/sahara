// expect: 42
// oracle: no
// the 39-digit maximum sizes the 40-byte buffer rule; 2^64 exercises
// the cross-word divide chain
#include "libc.c"
i64 ok(u8 *buf, u64 len, u8 *want) {
    if (strcmp(buf, want) != 0) { return 0; }
    if (len != strlen(want)) { return 0; }
    return 1;
}
i64 main() {
    u8 b[48];
    if (!ok(b, u128_to_dec(b, 0), "0")) { return 1; }
    if (!ok(b, u128_to_dec(b, 7), "7")) { return 2; }
    u128 two64 = (u128)1 << 64;
    if (!ok(b, u128_to_dec(b, two64), "18446744073709551616")) { return 3; }
    u128 ones = (u128)0 - 1;
    if (!ok(b, u128_to_dec(b, ones),
            "340282366920938463463374607431768211455")) { return 4; }
    return 42;
}
