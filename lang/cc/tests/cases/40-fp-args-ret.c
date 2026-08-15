// expect: 111906
// function pointers as argument and as return value
i64 inc(i64 x) { return x + 1; }
i64 dec(i64 x) { return x - 1; }
i64 apply(i64 (*f)(i64), i64 x) { return f(x); }
i64 (*pick(i64 k))(i64) { if (k) { return inc; } return dec; }
i64 main() {
    i64 a = apply(inc, 10);
    i64 b = apply(pick(0), 20);
    i64 (*g)(i64) = pick(1);
    return a * 10000 + b * 100 + g(5);
}
