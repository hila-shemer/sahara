// expect: 0x3dd626f0e77
// const: initialized const globals land in rodata (this case is the
// rodata-routing golden); const locals and pointer-to-const reads
const i64 factors[4] = { 2, 3, 5, 7 };
const u32 magic = 0xC0DE;
const u8 msg[6] = { 104, 101, 108, 108, 111, 0 };
i64 sum(const i64 *p, i64 n) {
    i64 s = 0, i;
    for (i = 0; i < n; i++) { s += p[i]; }
    return s;
}
i64 main() {
    const i64 local = 25;
    i64 t = sum(factors, 4) + local;             // 17+25
    t = t * 100000 + (i64)(u64)magic;            // 0xC0DE
    t = t * 1000 + (i64)msg[1];                  // 101
    u8 const *cp = msg;                          // trailing qualifier
    t = t * 1000 + (i64)cp[4];                   // 111
    return t;
}
