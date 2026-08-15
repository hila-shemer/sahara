// expect: 0xa9240578
// ?: branch-lowered: nesting, pointer arms, use as condition
i64 f(i64 x) { return x * 2; }
i64 main() {
    i64 a = 5, b = 9;
    i64 t = a < b ? 1 : 2;
    t = t * 10 + (a > b ? f(a) : f(b));          // 18
    t = t * 10 + (a ? b ? 3 : 4 : 5);            // nested: 3
    i64 *p = a < b ? &a : &b;
    *p = 77;                                     // a = 77
    t = t * 100 + a;
    t = t * 10 + (t ? 1 : 0);
    u8 small = 200;
    i64 big = -1000;
    t = t * 10000 + (a == 77 ? (i64)small : big); // common typing: 200
    return t;
}
