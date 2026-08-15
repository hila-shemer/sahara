// expect: 0x64fc70bf
// i8/i16/u16/i32/u32 as first-class storage; arithmetic through
// explicit common casts so C89 and cc semantics coincide (oracle on)
i64 main() {
    i8  a = -100;
    u8  b = 200;
    i16 c = -30000;
    u16 d = 60000;
    i32 e = -2000000000;
    u32 f = 4000000000;
    i64 t = 0;
    t = t + (i64)a * 3;
    t = t + (i64)b * 5;
    t = t + (i64)c - (i64)d;
    t = t + (i64)e / 7;
    t = t + (i64)(u64)f % 9973;
    e = e + 1;
    f = f + 1;
    a = (i8)(a + 1);
    d = (u16)(d + 1);
    t = t + (i64)e + (i64)(u64)f + (i64)a + (i64)d;
    i32 g = (i32)((i32)e / (i32)100);
    u32 h = (u32)((u32)f % (u32)1000);
    return t + (i64)g + (i64)(u64)h;
}
