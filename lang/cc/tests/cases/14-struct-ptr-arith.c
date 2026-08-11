// expect: 39
// pointer arithmetic with a non-power-of-two struct size (24)
struct V { i64 x; i64 y; u8 tag; };
i64 main() {
    struct V vs[5];
    i64 i = 0;
    while (i < 5) { vs[i].x = i * 7; i = i + 1; }
    struct V *p = vs;
    struct V *q = p + 4;
    i64 t = q->x;
    q = q - 3;
    t = t + q->x;
    t = t + (i64)(q - p);
    t = t + ((&vs[4]) - (&vs[1]));
    return t;
}
