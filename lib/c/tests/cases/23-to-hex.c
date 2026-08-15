// expect: 42
// oracle: no
// lowercase, no 0x, minimal digits; u128 all-ones is the 32-digit
// maximum behind the 33-byte buffer rule
#include "libc.c"
i64 ok(u8 *buf, u64 len, u8 *want) {
    if (strcmp(buf, want) != 0) { return 0; }
    if (len != strlen(want)) { return 0; }
    return 1;
}
i64 main() {
    u8 b[40];
    if (!ok(b, u64_to_hex(b, 0), "0")) { return 1; }
    if (!ok(b, u64_to_hex(b, 0xdeadbeef), "deadbeef")) { return 2; }
    if (!ok(b, u64_to_hex(b, 16), "10")) { return 3; }
    if (!ok(b, u64_to_hex(b, 0xFFFFFFFFFFFFFFFF), "ffffffffffffffff")) { return 4; }
    if (!ok(b, u128_to_hex(b, 0), "0")) { return 5; }
    u128 ones = (u128)0 - 1;
    if (!ok(b, u128_to_hex(b, ones), "ffffffffffffffffffffffffffffffff")) { return 6; }
    u128 big = ((u128)1 << 100) + 5;
    if (!ok(b, u128_to_hex(b, big), "10000000000000000000000005")) { return 7; }
    return 42;
}
