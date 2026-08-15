// expect: 42
// oracle: no
// the sign path, including i64 MIN - whose magnitude does not fit an
// i64, which is why the negate happens in u64 (wrap is defined)
#include "libc.c"
i64 ok(u8 *buf, u64 len, u8 *want) {
    if (strcmp(buf, want) != 0) { return 0; }
    if (len != strlen(want)) { return 0; }
    return 1;
}
i64 main() {
    u8 b[24];
    if (!ok(b, i64_to_dec(b, 0), "0")) { return 1; }
    if (!ok(b, i64_to_dec(b, -1), "-1")) { return 2; }
    if (!ok(b, i64_to_dec(b, 42), "42")) { return 3; }
    if (!ok(b, i64_to_dec(b, -10), "-10")) { return 4; }
    if (!ok(b, i64_to_dec(b, 9223372036854775807), "9223372036854775807")) { return 5; }
    i64 min = (i64)0x8000000000000000;
    if (!ok(b, i64_to_dec(b, min), "-9223372036854775808")) { return 6; }
    return 42;
}
