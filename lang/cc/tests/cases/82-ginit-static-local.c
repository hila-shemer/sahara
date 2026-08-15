// expect: 0x19d
// static locals with full initializers: arrays, strings, structs
struct S { i64 a; u16 b; };
i64 nth(i64 k) {
    static i64 primes[] = { 2, 3, 5, 7, 11 };
    static u8 name[] = "prime";
    static struct S s = { 1000, 42 };
    return primes[k] + (i64)name[0] * 0 + s.a / 1000 + (i64)s.b / 42;
}
i64 main() {
    return nth(0) * 100 + nth(4);        // (2+2)*100 + 13
}
