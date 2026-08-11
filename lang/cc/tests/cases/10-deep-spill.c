// expect: 2431
// deliberately deep expression: forces temp-stack spill past r15,
// with a call at the bottom (spill-across-call at depth > 8)
i64 g(i64 x) { return x * 2 + 1; }
i64 main() {
    i64 a = 1; i64 b = 2; i64 c = 3; i64 d = 4;
    return a + (b * (c + (d * (a + (b * (c + (d * (a + (b * (c
           + (d + g(5))))))))))));
}
