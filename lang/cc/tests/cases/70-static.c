// expect: 0x178a35fe3b
// static: file-scope functions and globals (mangled, uncollidable),
// static locals with constant init, static function through a pointer
static i64 counter_base = 100;
static i64 bump(i64 k) {
    static i64 count = 0;
    count += k;
    return counter_base + count;
}
static i64 twice(i64 x) { return 2 * x; }
i64 main() {
    i64 t = bump(1);             // 101
    t = t * 1000 + bump(2);      // 103
    i64 (*f)(i64) = twice;       // address of a static function
    t = t * 1000 + f(21);        // 42
    t = t * 1000 + bump(4);      // 107
    return t;
}
