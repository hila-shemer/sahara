// expect: 156
i64 main() {
    i64 a = 17; i64 b = 5;
    return (a + b) * 3 - a / b - a % b + (a << 2) + (b >> 1)
         + (a & b) + (a | b) + (a ^ b) + -a;
}
