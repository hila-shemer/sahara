// expect: 0xc00003f0
// oracle: no  (all of these are UB in host C; CC-M1 defines them)
i64 main() {
    i64 a = 7; i64 z = 0;
    i64 q = a / z;                       // all-ones quotient = -1
    i64 r = a % z;                       // remainder = dividend
    u64 uq = (u64)9 / (u64)z;            // u64 all-ones
    i64 m = (i64)0x8000000000000000;
    i64 mm = m / (0 - 1);                // MIN/-1 wraps to MIN
    i64 rr = m % (0 - 1);                // 0
    i64 sh = 1 << 64;                    // count mod 64: << 0
    i64 sh2 = 1 << 65;                   // << 1
    u64 shr = (u64)0x8000000000000000 >> 65;
    i64 mx = 9223372036854775807;
    i64 ovf = mx + 1;                    // two's-complement wrap
    i64 t = q + r + (i64)(uq >> 32) + (i64)(mm >> 32) + rr
          + sh + sh2 + (i64)(shr >> 32);
    if (ovf < 0) t = t + 1000;
    return t;
}
