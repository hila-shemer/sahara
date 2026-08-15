// expect: 0x3ae5
// volatile: accepted everywhere, trivially honored (no optimizer -
// every source access is a real access already)
volatile i64 vg = 5;
i64 main() {
    volatile i64 x = 10;
    volatile u32 *p = (volatile u32 *)&vg;       // low half on LE
    x = x + vg;
    *p = 77;
    return x * 1000 + vg;                        // 15 * 1000 + 77
}
