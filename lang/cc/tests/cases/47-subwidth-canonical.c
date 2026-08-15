// expect: 8589934596
// oracle: no
// the canonical-form corners (work-order risk 1): bit-31/15/7 images,
// 32-bit wrap, division corners at width 32 - cc/ISA semantics, so
// expects are hand-computed against cc-m1.md 4/5.3, not gcc
i64 main() {
    u32 x = 4294967295;
    x = x + 1;                     // wraps at 32: 0
    i64 t = (i64)(u64)x;
    u32 y = 2147483648;            // bit 31 set: the risky image
    t = t + (i64)(u64)y;           // zero-extends: +2147483648
    i32 z = -1;
    u32 w = (u32)z;                // same canonical image: 0xFFFFFFFF
    t = t + (i64)(u64)w;           // +4294967295
    u16 a = 65535;
    u16 b = 1;
    t = t + (i64)(a - b);          // promoted u64: +65534
    t = t + (i64)(b - a);          // u64 wrap, then i64: -65534
    u8 c = 1;
    u8 d = 2;
    u64 hp = c - d;                // m1 frozen deviation: huge positive
    t = t + (i64)hp;               // -1
    i8 m = -128;
    t = t + (i64)m;                // -128
    t = t + (i64)(u8)m;            // +128
    i16 s = -32768;
    t = t + (i64)s + (i64)(u16)s;  // -32768 + 32768 = 0
    u32 p2 = 65536;
    u32 q2 = p2 * p2;              // 2^32 wraps at 32: 0
    t = t + (i64)(u64)q2;
    i32 mn = -2147483647 - 1;
    i32 n1 = -1;
    i32 dv = mn / n1;              // sdiv.32 MIN/-1: quotient = MIN
    t = t + (i64)dv;               // -2147483648
    i32 r0 = mn % n1;              // srem.32 MIN/-1: remainder = 0
    t = t + (i64)r0;
    u32 z0 = 7;
    u32 zz = 0;
    u32 dz = z0 / zz;              // udiv.32 by zero: all-ones at 32
    u32 rz = z0 % zz;              // remainder = dividend
    t = t + (i64)(u64)dz + (i64)(u64)rz;   // +4294967295 +7
    return t;
}
