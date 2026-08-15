// cc-error
// function-pointer assignment needs the exact type (return differs)
i64 f(i64 x) { return x; }
i64 main() {
    u64 (*p)(i64);
    p = f;
    return 0;
}
