// expect: 42
// oracle: no
// minimal digits, "0" for zero, NUL-terminated, length returned -
// including the 20-digit maximum that sizes the 21-byte buffer rule
#include "libc.c"
i64 ok(u8 *buf, u64 len, u8 *want) {
    if (strcmp(buf, want) != 0) { return 0; }
    if (len != strlen(want)) { return 0; }
    return 1;
}
i64 main() {
    u8 b[24];
    if (!ok(b, u64_to_dec(b, 0), "0")) { return 1; }
    if (!ok(b, u64_to_dec(b, 1), "1")) { return 2; }
    if (!ok(b, u64_to_dec(b, 9), "9")) { return 3; }
    if (!ok(b, u64_to_dec(b, 10), "10")) { return 4; }
    if (!ok(b, u64_to_dec(b, 12345678901234567890), "12345678901234567890")) { return 5; }
    if (!ok(b, u64_to_dec(b, 0xFFFFFFFFFFFFFFFF), "18446744073709551615")) { return 6; }
    return 42;
}
