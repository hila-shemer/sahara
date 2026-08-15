// expect: 0xbf045f3a36
// all ten compound assignments, incl. through pointers and fields
struct S { i64 v; u32 w; };
i64 main() {
    i64 a = 100;
    a += 23; a -= 3; a *= 2; a /= 4; a %= 13;    // 60, 240/4=60, 60%13=8
    u64 m = 0xF0;
    m &= 0x3C; m |= 0x03; m ^= 0xFF;             // 0x30,0x33,0xCC
    i64 sh = 3;
    sh <<= 4; sh >>= 2;                          // 48, 12
    struct S s;
    s.v = 1000; s.w = 7;
    s.v += 11;
    s.w *= 3;                                    // u32: 21
    i64 arr[3];
    arr[0] = 1; arr[1] = 2; arr[2] = 3;
    i64 *p = arr;
    p += 2;
    *p -= 1;                                     // arr[2] = 2
    p -= 1;
    i64 t = a * 1000 + (i64)m;                   // 8*1000+204
    t = t * 100 + sh;
    t = t * 10000 + s.v + (i64)(u64)s.w;         // 1011+21=1032
    t = t * 100 + arr[2] * 10 + *p;              // 2*10+2
    return t;
}
