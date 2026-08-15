// expect: 0x070979f145294050
// ++/-- pre and post: value semantics, sub-width store wrap, pointers
i64 g = 100;
i64 main() {
    i64 a = 5;
    i64 t = a++;                 // t=5, a=6
    t = t * 100 + ++a;           // a=7, t=507
    t = t * 100 + a--;           // t=50707, a=6
    t = t * 100 + --a;           // a=5, t=5070705
    u8 b = 255;
    b++;                         // wraps at store: 0
    t = t * 10 + (i64)b;
    u8 c = 0;
    c--;                         // wraps: 255
    t = t + (i64)c - 255;
    g++; ++g;
    t = t * 100 + g;             // 102
    i64 arr[4];
    arr[0] = 10; arr[1] = 20; arr[2] = 30; arr[3] = 40;
    i64 *p = arr;
    t = t * 100 + *p++;          // 10, p -> arr[1]
    t = t * 100 + *++p;          // p -> arr[2], 30
    t = t * 100 + (--p)[0];      // p -> arr[1], 20
    arr[2]++;
    ++arr[2];
    t = t * 100 + arr[2];        // 32
    return t;
}
