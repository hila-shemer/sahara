// expect: 1149
// oracle: no
// null compare (literal 0) and the u64 cast round-trip
i64 sq(i64 x) { return x * x; }
i64 main() {
    i64 (*p)(i64) = (i64 (*)(i64))0;
    i64 r = 0;
    if (p == 0) { r = r + 1; }
    p = sq;
    if (p != 0) { r = r + 10; }
    u64 bits = (u64)p;
    i64 (*q)(i64) = (i64 (*)(i64))bits;
    return r * 100 + q(7);
}
