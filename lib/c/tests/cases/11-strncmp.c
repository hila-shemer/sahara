// expect: 42
// strncmp: n = 0 answers 0, the limit stops the walk, NUL stops it too
#include "libc.c"
i64 sgn(i64 x) { if (x < 0) { return -1; } if (x > 0) { return 1; } return 0; }
i64 main() {
    if (strncmp("abc", "xyz", 0) != 0) { return 1; }
    if (sgn(strncmp("abcdef", "abcxyz", 3)) != 0) { return 2; }
    if (sgn(strncmp("abcdef", "abcxyz", 4)) != -1) { return 3; }
    if (sgn(strncmp("abc", "abc", 100)) != 0) { return 4; }
    if (sgn(strncmp("ab", "abc", 5)) != -1) { return 5; }
    if (sgn(strncmp("abc", "ab", 5)) != 1) { return 6; }
    return 42;
}
