// cc-error
// ++ needs an lvalue
i64 main() {
    i64 a = 1, b = 2;
    ++(a + b);
    return 0;
}
