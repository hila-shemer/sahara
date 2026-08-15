// expect: 0x36fe8d4
// typedef: scoped aliases, pointer/array/fnptr typedefs, and the
// port-compat hook (i32 under a friendlier name)
typedef i32 myint;
typedef u8 *bytep;
typedef i64 vec4[4];
typedef i64 (*binop)(i64, i64);
typedef struct Pair { myint a; myint b; } Pair;
i64 addf(i64 x, i64 y) { return x + y; }
i64 mulf(i64 x, i64 y) { return x * y; }
i64 main() {
    myint m = -5;
    Pair p;
    p.a = 3; p.b = 4;
    vec4 v;
    v[0] = 10; v[3] = 40;
    bytep s = (bytep)"AB";
    binop op = addf;
    i64 t = (i64)m + p.a * p.b + v[0] + v[3];    // -5+12+50 = 57
    t = t * 100 + (i64)s[1];                     // 'B' = 66
    t = t * 10 + op(2, 3);                       // 5
    op = mulf;
    t = t * 10 + op(2, 3);                       // 6
    {
        typedef i64 myint;                       // block-scope retype
        myint big = 1000000000000;
        t = t + (big / 1000000000000);           // +1
    }
    t = t * 100 + (i64)sizeof(myint) * 10 + (i64)sizeof(Pair);
    return t;
}
