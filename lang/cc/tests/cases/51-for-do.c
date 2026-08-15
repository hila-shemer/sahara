// expect: 0x1910660c
// for (incl. empty clauses) and do-while over the loop machinery
i64 main() {
    i64 t = 0;
    i64 i;
    for (i = 0; i < 10; i = i + 1) {
        if (i == 3) { continue; }        // continue -> step
        t = t + i;
    }
    for (i = 0; ; i = i + 1) {           // empty condition: infinite
        if (i == 5) { break; }
    }
    t = t * 100 + i;
    i64 j = 7;
    for (;;) {                           // all clauses empty
        j = j - 1;
        if (j == 0) { break; }
    }
    t = t * 10 + j;
    i64 k = 0;
    do {
        k = k + 1;
    } while (k < 5);
    t = t * 10 + k;                      // body runs, then test
    i64 m = 0;
    do { m = m + 100; } while (0);       // exactly once
    return t * 1000 + m;
}
