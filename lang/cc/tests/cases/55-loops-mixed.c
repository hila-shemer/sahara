// expect: 0x1a6
// binding rules: break binds to the nearest loop-or-switch, continue
// to the nearest loop only - a switch inside a loop is the test
i64 main() {
    i64 t = 0;
    i64 i;
    for (i = 0; i < 6; i = i + 1) {
        switch (i % 3) {
        case 0:
            t = t + 1;
            break;                       // exits the switch, not the loop
        case 1:
            continue;                    // skips the tail, next iteration
        default:
            t = t + 10;
        }
        t = t + 100;                     // skipped when i % 3 == 1
    }
    return t;
}
