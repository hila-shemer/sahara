// expect: 2534
// break/continue nesting (named hard case)
i64 main() {
    i64 sum = 0; i64 i = 0;
    while (i < 10) {
        i = i + 1;
        if (i == 3) continue;
        if (i == 8) break;
        i64 j = 0;
        while (j < i) {
            j = j + 1;
            if (j == 2) continue;
            if (j > 4) break;
            sum = sum + j;
        }
        sum = sum + i * 100;
    }
    return sum;
}
