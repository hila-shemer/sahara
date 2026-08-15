// second unit of 84-multi-basic: defines the extern global, uses the
// same struct tag with the identical layout, calls back into unit 0
struct Pt { i64 x; i64 y; };
i64 shared_base = 100;
extern i64 shift(struct Pt p);
i64 magnify(struct Pt p, i64 k) { return (p.x + p.y) * k; }
