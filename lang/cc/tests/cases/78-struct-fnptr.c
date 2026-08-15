// expect: 0x1df7e01
// the two features composed: function pointers that take and return
// structs (indirect sret - reserve-and-shift through jalr)
struct P { i64 x; i64 y; };
struct P padd(struct P a, struct P b) {
    struct P r;
    r.x = a.x + b.x; r.y = a.y + b.y;
    return r;
}
struct P swap(struct P a, struct P b) {
    struct P r;
    r.x = b.y; r.y = a.x;
    return r;
}
i64 main() {
    struct P (*op)(struct P, struct P) = padd;
    struct P a, b;
    a.x = 1; a.y = 2; b.x = 30; b.y = 40;
    struct P r = op(a, b);               // {31, 42}
    i64 t = r.x * 100 + r.y;
    op = swap;
    r = op(a, b);                        // {40, 1}
    t = t * 10000 + r.x * 100 + r.y;
    return t;
}
