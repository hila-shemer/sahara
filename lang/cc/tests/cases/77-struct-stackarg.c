// expect: 0x323408
// an aggregate argument in the >8-argument stack-slot region (its
// ADDRESS rides the 16-byte slot), plus one in a register position
struct W { i64 a; i64 b; i64 c; };
i64 wide(i64 x0, i64 x1, i64 x2, i64 x3, i64 x4, i64 x5, i64 x6,
         i64 x7, struct W w, i64 x9) {
    return x0 + x1 + x2 + x3 + x4 + x5 + x6 + x7
         + w.a * 2 + w.b * 3 + w.c * 5 + x9 * 7;
}
i64 first(struct W w, i64 k) { return w.a + w.b * k + w.c; }
i64 main() {
    struct W w;
    w.a = 10; w.b = 20; w.c = 30;
    i64 t = wide(1, 2, 3, 4, 5, 6, 7, 8, w, 9);
    // 36 + 20+60+150 + 63 = 329
    t = t * 10000 + first(w, 4);         // 10+80+30 = 120
    return t;
}
