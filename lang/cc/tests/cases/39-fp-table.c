// expect: 112307
// dispatch through a function-pointer field in an array of structs
struct op { i64 tag; i64 (*fn)(i64, i64); };
i64 add2(i64 a, i64 b) { return a + b; }
i64 mul2(i64 a, i64 b) { return a * b; }
i64 sub2(i64 a, i64 b) { return a - b; }
i64 main() {
    struct op t[3];
    t[0].tag = 1; t[0].fn = add2;
    t[1].tag = 2; t[1].fn = mul2;
    t[2].tag = 3; t[2].fn = sub2;
    i64 acc = 0;
    i64 i = 0;
    while (i < 3) {
        acc = acc * 100 + t[i].fn(7, 3) + t[i].tag;
        i = i + 1;
    }
    return acc;
}
