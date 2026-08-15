// expect: 0x1a21b
// input: inputs/84b.c
// two-unit compile (the two-input golden): cross-file extern global
// and function use, struct-by-name defined identically in both files
struct Pt { i64 x; i64 y; };
extern i64 shared_base;
extern i64 magnify(struct Pt p, i64 k);
i64 shift(struct Pt p) { return p.x + p.y + shared_base; }
i64 main() {
    struct Pt p;
    p.x = 3; p.y = 4;
    i64 t = shift(p);                    // 3+4+100
    t = t * 1000 + magnify(p, 5);        // (3+4)*5 = 35
    return t;
}
