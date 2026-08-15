// expect: 0x16e5d32
// aggregate returns: hidden result pointer, returns feeding calls
// and assignments directly - the struct copy in/out golden
struct P { i64 x; i64 y; };
struct P mk(i64 a, i64 b) {
    struct P p;
    p.x = a; p.y = b;
    return p;
}
struct P flip(struct P p) {
    struct P r;
    r.x = p.y; r.y = p.x;
    return r;
}
i64 dot(struct P a, struct P b) { return a.x * b.x + a.y * b.y; }
i64 main() {
    struct P p = mk(3, 4);
    struct P q;
    q = flip(p);                         // q = {4,3}
    i64 t = dot(p, q);                   // 12+12 = 24
    t = t * 1000 + dot(mk(1, 2), flip(mk(3, 4)));  // 1*4+2*3 = 10
    struct P r = flip(flip(p));          // composition round-trip
    t = t * 1000 + r.x * 10 + r.y;       // 34
    return t;
}
