// expect: 0x7569
// the comma operator: value is the right operand, effects in order;
// DOOM-style for-headers
i64 main() {
    i64 a = 1, b = 2, t;
    t = (a = 10, b = 20, a + b);                 // 30
    i64 i, j;
    for (i = 0, j = 10; i < j; i++, j--) { }
    t = t * 100 + i;                             // meet at 5
    t = t * 10 + (a, b, 7);
    return t;
}
