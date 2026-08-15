// expect: 3092425448
// oracle: no
// the pinned conversion lowerings in one cluster (cc-m1.md 4) - this
// is the sub-width conversion golden
i64 main() {
    i64 big = 0x123456789ABCDEF0;
    i8 a = (i8)big;                // or.64 sxt 8: -16
    u8 b = (u8)big;                // and 0xff (frozen m1 row): 240
    i16 c = (i16)big;              // or.64 sxt 16: -8464
    u16 d = (u16)big;              // or.64 zxt 16: 57072
    i32 e = (i32)big;              // or.32: -1698898192
    u32 f = (u32)big;              // or.32: same image, u32 2596069104
    u64 g = (u64)f;                // or.64 zxt 32
    i64 h = (i64)e;                // no code: image is the sext
    i128 w = (i128)g;              // shl/shr pair (u64 -> 128)
    u128 v = (u128)e;              // no code: i32 image is the value
    i64 t = (i64)a + (i64)b + (i64)c + (i64)d;
    t = t + (i64)e + (i64)(u64)f + (i64)g + h;
    t = t + (i64)(w >> 1) + (i64)(v & 0xFF);
    return t;
}
