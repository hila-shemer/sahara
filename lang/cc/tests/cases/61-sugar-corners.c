// expect: 22048575
// oracle: no
// sugar at the canonical-form corners: u32 compound wrap, shift-mod,
// ternary keeping u32 canonical through widening
i64 main() {
    u32 x = 0x80000000;
    x += 0x80000000;             // wraps at 32: 0
    i64 t = (i64)(u64)x;         // 0
    u32 y = 1;
    y <<= 33;                    // count mod 32: <<1 = 2
    t = t * 10 + (i64)(u64)y;    // 2
    i32 z = -8;
    z >>= 1;                     // arithmetic: -4
    t = t * 10 + (z == -4 ? 1 : 0);      // 21
    u32 big = 0xFFFFFFFF;
    u64 w = (t > 0) ? (u64)big : 0;      // widening keeps zero-extension
    t = t * 1000000 + (i64)(w >> 12);    // 21 * 1e6 + 0xFFFFF
    i64 n = 5;
    n *= -1, n += 1;             // comma at statement level: n = -4
    return t + n + 4;            // 21000000 + 1048575 - 4 + 4 ... compute
}
