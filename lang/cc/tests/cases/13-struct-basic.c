// expect: 1406080
// . / -> / array-of-struct / nested struct / sizeof layout rules
struct V { i64 x; i64 y; u8 tag; };
struct W { struct V v; i64 arr[3]; u8 b; };
i64 main() {
    struct V a;
    struct W w;
    struct V vs[4];
    a.x = 11; a.y = 22; a.tag = (u8)7;
    w.v.x = 100; w.arr[2] = 55; w.b = (u8)200;
    vs[3].x = 1000;
    struct V *p = &a;
    p->y = 33;
    i64 t = a.x + a.y + (i64)a.tag + w.v.x + w.arr[2] + (i64)w.b
          + vs[3].x;
    return t * 1000 + (i64)sizeof(struct V) + (i64)sizeof(struct W);
}
