// expect: 605
// >8 arguments, both caller and callee sides, including pass-through
i64 wsum(i64 a, i64 b, i64 c, i64 d, i64 e, i64 f, i64 g, i64 h,
         i64 i, i64 j) {
    return a + 2*b + 3*c + 4*d + 5*e + 6*f + 7*g + 8*h + 9*i + 10*j;
}
i64 pass(i64 a, i64 b, i64 c, i64 d, i64 e, i64 f, i64 g, i64 h,
         i64 i, i64 j) {
    return wsum(j, i, h, g, f, e, d, c, b, a);
}
i64 main() {
    return wsum(1,2,3,4,5,6,7,8,9,10) + pass(1,2,3,4,5,6,7,8,9,10);
}
