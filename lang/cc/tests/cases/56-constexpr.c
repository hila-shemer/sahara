// expect: 142132045
// the grown constant-expression grammar: / % comparisons && || ! and
// casts, evaluated at compile time (runtime / % stay unfolded - 5.5)
u64 g1 = 1000 / 7;
i64 g2 = (3 < 5) && !(2 != 2);
u8 tab[256 / 8];
i64 g3 = (i64)(u8)300;
u64 g4 = 100 % 9;
i64 main() {
    i64 t = (i64)g1 * 1000 + g2 * 100 + (i64)(tab[0] + 32);   // tab is bss: zero
    t = t * 1000 + g3 + (i64)g4;
    switch (t % 10) {
    case 45 / 9:                         // 5
        return t;
    default:
        return 0;
    }
}
