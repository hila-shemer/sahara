// expect: 97
// bss-is-zero by the loader contract
struct S { i64 a; u8 b; };
i64 zeroed[10];
u128 wz;
struct S gs;
i64 main() {
    i64 t = 0; i64 i = 0;
    while (i < 10) { t = t + zeroed[i]; i = i + 1; }
    if (wz == 0) t = t + 1;
    if (gs.a == 0) t = t + 2;
    if (gs.b == 0) t = t + 4;
    zeroed[3] = 9;
    t = t + zeroed[3] * 10;
    return t;
}
