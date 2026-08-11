// expect: 7
// the pinned literal typing rule (i64, then u64, then i128, u128)
i64 main() {
    i64 t = 0;
    if (0x8000000000000000 > 0) t = t + 1;
    if (0 - 1 < 1) t = t + 2;
    u64 m = 0xffffffffffffffff;
    if (m == 0 - 1) t = t + 4;
    return t;
}
