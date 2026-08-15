// expect: 220
// >8 arguments through a function pointer (stack-slot args + jalr)
i64 sum10(i64 a, i64 b, i64 c, i64 d, i64 e, i64 f, i64 g, i64 h,
          i64 i, i64 j) {
    return a + 2*b + 3*c + 4*d + 5*e + 6*f + 7*g + 8*h + 9*i + 10*j;
}
i64 main() {
    i64 (*p)(i64,i64,i64,i64,i64,i64,i64,i64,i64,i64) = sum10;
    return p(1,2,3,4,5,6,7,8,9,10) - sum10(1,2,3,4,5,6,7,8,9,10)
         + p(10,9,8,7,6,5,4,3,2,1);
}
