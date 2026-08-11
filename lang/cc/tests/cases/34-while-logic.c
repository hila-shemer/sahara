// expect: 5511
i64 main() {
    i64 i = 0; i64 t = 0;
    while (i < 20 && t < 50) { t = t + i; i = i + 1; }
    return t * 100 + i;
}
