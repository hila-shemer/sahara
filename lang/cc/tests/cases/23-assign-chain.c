// expect: 604
// assignment is an expression; value = the stored (converted) value
i64 main() {
    i64 a; i64 b; i64 c;
    a = b = c = 5;
    u8 x;
    i64 v = (i64)(x = (u8)300);
    i64 arr2[3];
    arr2[a = 1] = 9;
    return a*1 + b*10 + c*100 + v + arr2[1];
}
