// expect: 63
// the classic canonical-form trap: u64 values whose image is negative
u64 main() {
    u64 big = 0xffffffffffffffff;
    u64 t = 0;
    if (big > 1000) t = t + 1;
    if (big / 3 == 0x5555555555555555) t = t + 2;
    if (big % 10 == 5) t = t + 4;
    u64 h = 0x8000000000000000;
    if (h > 0x7fffffffffffffff) t = t + 8;
    if (h >> 1 == 0x4000000000000000) t = t + 16;
    if ((i64)h < 0) t = t + 32;
    return t;
}
