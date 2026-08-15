// expect: 0x51826784712
// enums: auto/explicit values, i32 representation, case labels,
// constant expressions, local shadowing
enum Color { RED, GREEN = 5, BLUE, BIG = 1000000 };
enum { ANON = 42 };
i64 tab[BLUE];
i64 main() {
    i64 t = RED * 100 + GREEN * 10 + BLUE;      // 0,5,6 -> 56... 0*100+50+6
    t = t * 10000 + (BIG / 10000);              // +100
    t = t + (i64)sizeof(enum Color) * 7;        // +4*7
    enum Color c = GREEN;
    switch (c) {
    case RED:   t = t * 10 + 1; break;
    case GREEN: t = t * 10 + 2; break;
    default:    t = t * 10 + 3;
    }
    {
        i64 RED = 77;                            // shadows the enumerator
        t = t * 100 + RED;
    }
    t = t * 10 + RED;                            // back in scope: 0
    t = t * 10 + ANON / 6;                       // 7
    t = t * 100 + (i64)(tab[0] + sizeof(tab) / sizeof(tab[0]));  // 6
    return t;
}
