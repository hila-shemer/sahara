// expect: 0xffffffffffffffffc2039bb807526820
// oracle: no
// unions: offset-0 members, size/align, defined little-endian punning
// (DOOM's fixed/angle trick) - byte reinterpretation is spec'd
union Pun { u32 w; u16 h[2]; u8 b[4]; };
union Wide { u64 q; u32 w[2]; };
struct Holder { u8 tag; union Pun p; };
i64 main() {
    union Pun u;
    u.w = 0x12345678;
    i64 t = (i64)u.b[0];                 // LE: 0x78
    t = t * 1000 + (i64)u.h[1];          // 0x1234
    u.b[3] = 0xFF;
    t = t * 100000 + (i64)(u64)(u.w >> 16);  // 0xFF34
    union Wide w;
    w.q = 0xAABBCCDD11223344;
    t = t * 100000 + (i64)(u64)(w.w[1] & 0xFFFF);   // 0xCCDD
    struct Holder h;
    h.tag = 9;
    h.p.w = 256;
    t = t * 1000 + (i64)h.tag * 100 + (i64)h.p.b[1];  // 900 + 1
    return t * 100 + (i64)sizeof(union Pun) + (i64)sizeof(struct Holder);
}
