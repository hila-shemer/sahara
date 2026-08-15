// expect: 0x100000206
// sub-width types as pointer indexes: i32 rides its canonical image,
// u32 zero-extends, promoted u8/u16/i8/i16 ride the 64-bit path
i64 main() {
    i64 arr[16];
    i64 i = 0;
    while (i < 16) { arr[i] = i * 10; i = i + 1; }
    i8  a = 3;
    u8  b = 5;
    i16 c = 7;
    u16 d = 9;
    i32 e = 11;
    u32 f = 13;
    i64 t = arr[a] + arr[b] + arr[c] + arr[d] + arr[e] + arr[f];
    i32 back = -4;
    i64 *p = &arr[8];
    t = t + p[back];
    u32 big = 4294967295;
    i64 *q = arr + big;          // zero-extended: arr + 0xFFFFFFFF
    t = t + (i64)(q - arr);      // == 4294967295
    i32 neg = -1;
    i64 *r2 = arr + neg;         // canonical image: arr - 1
    t = t + (i64)(r2 - arr);     // == -1
    return t;
}
