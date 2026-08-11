// expect: 775
// u8 promotes to u64; these stay in the host-agreeing range
i64 main() {
    u8 a = 200; u8 b = 100;
    i64 t = (i64)(a + b);
    u8 c = (u8)(a + b);
    t = t + (i64)c * 10;
    if (a > b) t = t + 1;
    u8 d = (u8)(a * b);
    t = t + (i64)d;
    t = t + (i64)(a / b);
    return t;
}
