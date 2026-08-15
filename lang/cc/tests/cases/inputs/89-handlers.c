// unit 2 of the DOOM-shaped case: the handlers, the address-
// initialized state table, and the rodata lookup table. Note the
// same-named static 'chk' - per-unit statics must not collide.
typedef struct StateDef { i32 tag; u16 next; i64 (*fn)(i32); } StateDef;
const i32 wave[16] = { 0, 3, 6, 8, 9, 8, 6, 3, 0, -3, -6, -8, -9,
                       -8, -6, -3 };
static i64 chk = 0;                    // counts calls in THIS unit
static i64 count(i64 v) { chk++; return v; }
i64 h_idle(i32 k) { return count((i64)wave[k]); }
i64 h_run(i32 k) { return count((i64)k * 2 + 1); }
i64 h_jump(i32 k) { return count((i64)wave[15 - k] - k); }
i64 h_pain(i32 k) { return count(-(i64)k); }
i64 h_die(i32 k) { return count((i64)(k * k)); }
StateDef states[5] = {
    { 0, 2, h_idle },
    { 1, 3, h_run },
    { 2, 4, h_jump },
    { 5, 0, h_pain },
    { 7, 1, h_die },
};
i64 handler_calls() { return chk; }
