// expect: 42030
// oracle: no
// fixture: fnlib.s
// interop both ways: C calls a .s function through a pointer, and a
// .s function jalr's a C function handed to it as a pointer
extern i64 fn_double(i64 x);
extern i64 fn_dispatch(i64 (*f)(i64), i64 x);
i64 triple(i64 x) { return x * 3; }
i64 main() {
    i64 (*p)(i64) = fn_double;
    i64 a = p(21);
    i64 b = fn_dispatch(triple, 10);
    return a * 1000 + b;
}
