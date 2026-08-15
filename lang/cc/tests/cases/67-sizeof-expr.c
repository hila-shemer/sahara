// expect: 124010032008008
// oracle: no
// sizeof on expressions: unpromoted lvalue types, unevaluated;
// sizeof(b + h) is 8 here (64-bit promotion deviation; C says 4)
// operands (the call must NOT run), arrlen in constant expressions
u16 warr[10];
i64 grid[3][4];
u64 hits = 0;
u64 bump() { hits = hits + 1; return hits; }
i64 main() {
    u8 b = 0;
    u16 h = 0;
    i32 w = 0;
    i64 t = (i64)(sizeof(b) * 100 + sizeof(h) * 10 + sizeof(w));  // 121... 1*100+2*10+4
    t = t * 1000 + (i64)(sizeof(warr) / sizeof(warr[0]));         // 10
    t = t * 1000 + (i64)sizeof(grid[0]);                          // 32
    t = t * 1000 + (i64)sizeof(bump());       // u64: 8 - and NO call
    t = t * 10 + (i64)hits;                   // still 0
    t = t * 100 + (i64)sizeof(b + h);         // promoted arithmetic: 8
    return t;
}
