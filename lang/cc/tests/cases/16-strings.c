// expect: 131150665
// strlen-in-C over string literals (u8 promotion via ldz.8)
i64 slen(u8 *s) { i64 n = 0; while (s[n]) n = n + 1; return n; }
i64 main() {
    u8 *h = "hello, sahara";
    i64 t = slen(h);
    t = t * 1000 + (i64)h[7];
    u8 *e = "";
    t = t * 10 + slen(e);
    u8 *x = "a\tb\nc\x41";
    t = t * 1000 + slen(x) * 100 + (i64)x[5];
    return t;
}
