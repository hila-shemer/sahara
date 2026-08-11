// expect: 144628800
// frames + ra discipline under recursion
i64 fib(i64 n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}
i64 fact(i64 n) {
    if (n == 0) return 1;
    return n * fact(n - 1);
}
i64 main() { return fib(12) * 1000000 + fact(10) % 1000000; }
