// expect: 81081017
// direct-vs-indirect agreement: same function, jal and jalr paths;
// &f == f; (*p)(x) == p(x). Also the indirect-call golden.
i64 sq(i64 x) { return x * x; }
i64 main() {
    i64 (*p)(i64);
    p = sq;
    i64 a = sq(9);
    i64 b = p(9);
    i64 c = (*p)(4);
    i64 (*q)(i64) = &sq;
    return a * 1000000 + b * 1000 + c + (p == q);
}
