// expect: 42
// strcmp orders by UNSIGNED byte value - the \xff case is where a
// signed-char host implementation would disagree; C mandates unsigned
// here too, so the oracle leg holds.
#include "libc.c"
i64 sgn(i64 x) { if (x < 0) { return -1; } if (x > 0) { return 1; } return 0; }
i64 main() {
    if (sgn(strcmp("", "")) != 0) { return 1; }
    if (sgn(strcmp("abc", "abc")) != 0) { return 2; }
    if (sgn(strcmp("abc", "abd")) != -1) { return 3; }
    if (sgn(strcmp("abd", "abc")) != 1) { return 4; }
    if (sgn(strcmp("ab", "abc")) != -1) { return 5; }
    if (sgn(strcmp("abc", "ab")) != 1) { return 6; }
    if (sgn(strcmp("a\xff", "a\x01")) != 1) { return 7; }
    return 42;
}
