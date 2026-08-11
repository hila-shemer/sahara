// expect: 15
// the u64 -> u128 zero-extension lowering (shl 64; shr 64)
i64 main() {
    u64 x = 0xdeadbeefcafebabe;
    u128 w = (u128)x;
    u64 t = 0;
    if ((u64)(w >> 64) == 0) t = t + 1;
    if (w < ((u128)1 << 100)) t = t + 2;
    i128 m = (i128)(0 - 1);
    if ((u64)(m >> 64) == 0xffffffffffffffff) t = t + 4;
    if ((u64)((w + w) >> 64) == 1) t = t + 8;
    return (i64)t;
}
