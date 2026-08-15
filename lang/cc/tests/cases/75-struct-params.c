// expect: 0x613faeae2
// by-value parameters: callee mutation invisible, &param points at
// the call's own staging copy, recursion with struct params
struct V { i64 x; i64 y; };
i64 consume(struct V v) {
    v.x = v.x * 2;                       // caller must not see this
    i64 *p = &v.x;                       // legal: the staging copy
    *p = *p + 1;
    return v.x + v.y;
}
i64 rsum(struct V v, i64 depth) {
    if (depth == 0) { return v.x + v.y; }
    v.x = v.x + 1;
    v.y = v.y - 1;
    return rsum(v, depth - 1);           // fresh copy per call
}
i64 main() {
    struct V a;
    a.x = 10; a.y = 5;
    i64 t = consume(a);                  // 21+5 = 26... (10*2+1)+5
    t = t * 1000 + a.x * 10 + a.y;       // unchanged: 105
    t = t * 1000 + rsum(a, 3);           // still 15
    t = t * 1000 + a.x;                  // 10
    return t;
}
