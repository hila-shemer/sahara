// expect: 0x753d4e5b150b71
// nested global initializers: arrays of structs, inner arrays,
// partial zero-fill, sub-width rows (.half/.word), union first-member
struct P { i16 x; i16 y; };
struct Rec { i32 tag; struct P pts[3]; u8 flags; };
struct Rec recs[3] = {
    { 1, { { 10, -10 }, { 20, -20 }, { 30, -30 } }, 7 },
    { 2, { { 5, 6 } }, 9 },
};
u16 waves[8] = { 100, 200, 300 };
i32 grid[2][3] = { { 1, 2, 3 }, { -4, -5, -6 } };
union U { u32 w; u8 b[4]; };
union U uu = { 0x11223344 };
i64 main() {
    i64 t = 0, i;
    for (i = 0; i < 3; i++) {
        t = t * 10 + recs[i].tag + recs[i].pts[0].x / 5;
    }
    t = t * 100 + recs[1].pts[1].x + recs[2].flags;      // 0 + 0
    t = t * 1000 + recs[0].pts[2].y + (i64)recs[1].flags;  // -30+9
    t = t * 10000 + (i64)waves[1] + (i64)waves[5];       // 200
    t = t * 100 + grid[1][2] + grid[0][1];               // -4
    t = t * 1000 + (i64)uu.b[3];                         // 0x11
    return t;
}
