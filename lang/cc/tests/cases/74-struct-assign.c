// expect: 0x108743a9c56b409b
// aggregate assignment: nested structs, unions, the odd-size align-1
// struct (u8[7]: unit-1 loop copy), self-assignment and aliased
// pointers (forward copy is the defined behavior)
struct Odd { u8 b[7]; };
struct Inner { i32 a; u16 b; };
struct Outer { struct Inner in; i64 arr[2]; u8 t; };
union Pack { u32 w; u8 b[4]; };
i64 main() {
    struct Odd o1, o2;
    i64 i;
    for (i = 0; i < 7; i++) { o1.b[i] = (u8)(i * 3 + 1); }
    o2 = o1;
    o1.b[0] = 99;                        // o2 keeps its copy
    struct Outer x, y;
    x.in.a = -5; x.in.b = 60000;
    x.arr[0] = 111; x.arr[1] = 222; x.t = 7;
    y = x;
    y.in.a = 1000;                       // x untouched
    struct Outer *p = &x, *q = &x;
    *p = *q;                             // aliased: defined, a no-op
    x = x;                               // self-assign: defined
    union Pack u1, u2;
    u1.w = 0x11223344;
    u2 = u1;
    i64 t = (i64)o2.b[0] + (i64)o2.b[6] + (i64)o1.b[0];  // 1+19+99
    t = t * 10000 + x.in.a + y.in.a;     // -5+1000
    t = t * 10000 + x.arr[1] + (i64)x.t; // 229
    t = t * 1000 + (i64)u2.b[2];         // 0x22
    struct Inner z = x.in;               // copy-initialization
    t = t * 100000 + z.a + (i64)z.b;     // -5+60000
    return t;
}
