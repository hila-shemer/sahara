// cc-error
// braces are required at each aggregate level (documented
// simplification: no C89 fill-in-order flattening)
struct P { i64 x; i64 y; };
struct P ps[2] = { 1, 2, 3, 4 };
i64 main() { return 0; }
