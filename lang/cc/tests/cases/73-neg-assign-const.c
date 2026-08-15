// cc-error
// assignment through a const lvalue is a compile error
const i64 k = 5;
i64 main() {
    k = 6;
    return 0;
}
