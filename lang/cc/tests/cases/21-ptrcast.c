// expect: 15
// oracle: no  (pointer width differs on the host)
i64 g = 77;
i64 main() {
    i64 *p = &g;
    u64 a = (u64)p;
    i64 *q = (i64*)a;
    u128 w = (u128)p;
    i64 *r = (i64*)w;
    i64 t = 0;
    if (*q == 77) t = t + 1;
    if (*r == 77) t = t + 2;
    if (q == p) t = t + 4;
    u8 *b = (u8*)p;
    if ((i64)*b == 77) t = t + 8;
    return t;
}
