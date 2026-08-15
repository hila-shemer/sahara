// expect: 42
#include "libc.c"
i64 main() {
    if (strlen("") != 0) { return 1; }
    if (strlen("a") != 1) { return 2; }
    if (strlen("hello, sahara") != 13) { return 3; }
    u8 buf[8];
    buf[0] = 'x'; buf[1] = 0; buf[2] = 'y'; buf[3] = 0;
    if (strlen(buf) != 1) { return 4; }   /* stops at the first NUL */
    return 42;
}
