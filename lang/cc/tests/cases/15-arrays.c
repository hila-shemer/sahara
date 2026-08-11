// expect: 446
i64 main() {
    i64 a[8];
    u8 bytes[16];
    i64 i = 0;
    while (i < 8) { a[i] = i * i; i = i + 1; }
    i = 0;
    while (i < 16) { bytes[i] = (u8)(i * 17); i = i + 1; }
    i64 t = 0;
    i = 0;
    while (i < 8) { t = t + a[i]; i = i + 1; }
    t = t + (i64)bytes[15];
    t = t + (i64)bytes[1];
    i64 *p = a;
    t = t + p[3] + *(p + 5);
    return t;
}
