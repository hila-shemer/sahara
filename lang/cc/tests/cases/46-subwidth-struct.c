// expect: 0x7141dce4a4
// mixed-width struct layout: natural alignment agrees with the host
struct M { u8 a; u16 b; i32 c; i64 d; u8 e; };
struct N { i16 x[3]; u32 y[2]; };
i64 main() {
    struct M m;
    struct N n;
    m.a = 250; m.b = 65000; m.c = -123456789; m.d = 987654321; m.e = 7;
    n.x[0] = -5; n.x[1] = 6; n.x[2] = -7;
    n.y[0] = 100000; n.y[1] = 4000000000;
    i64 t = (i64)m.a + (i64)m.b + (i64)m.c + m.d + (i64)m.e;
    t = t + (i64)n.x[0] * (i64)n.x[1] * (i64)n.x[2];
    t = t + (i64)(u64)n.y[0] + (i64)(u64)n.y[1];
    return t * 100 + (i64)sizeof(struct M) + (i64)sizeof(struct N);
}
