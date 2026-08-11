// expect: 101
// oracle: no  (dedup of identical literals is pinned by cc-m1.md 5.4;
// host C makes no such promise)
i64 main() {
    u8 *a = "same";
    u8 *b = "same";
    u8 *c = "different";
    i64 t = 0;
    if (a == b) t = t + 1;
    if (a == c) t = t + 10;
    if (*a == *b) t = t + 100;
    return t;
}
