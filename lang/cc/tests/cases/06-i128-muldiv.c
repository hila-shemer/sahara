// expect: 0xffffffffffffffffffffbafb0e59bb87
// native 128-bit multiply/divide vs the oracle's __int128
i64 main() {
    i128 a = (i128)123456789123 * (i128)987654321987;
    i128 b = a / (i128)1000003;
    i128 r = a % (i128)1000003;
    i128 n = (i128)0 - a;
    u128 ua = (u128)a;
    u128 q = ua / (u128)12345;
    return (i64)((a ^ b ^ r ^ n ^ (i128)q) % (i128)0xffffffffffff);
}
