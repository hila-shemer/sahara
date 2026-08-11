// expect: 63
i64 main() {
    i64 t = 0;
    i64 big = (i64)0x7fffffffffffffff;
    u64 u = (u64)big + 1;
    if ((i64)u == 0 - big - 1) t = t + 1;
    i128 w = (i128)(i64)(0 - 1);
    if ((u64)w == 0xffffffffffffffff) t = t + 2;
    u128 uw = (u128)(u64)(0 - 1);
    if ((u64)(uw >> 64) == 0) t = t + 4;
    u8 b = (u8)0x1ff;
    if (b == 255) t = t + 8;
    i64 back = (i64)(u128)(u64)12345;
    if (back == 12345) t = t + 16;
    if ((u8)300 == 44) t = t + 32;
    return t;
}
