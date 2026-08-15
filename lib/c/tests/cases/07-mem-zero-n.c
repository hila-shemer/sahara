// expect: 42
// n = 0 is a defined no-op for the whole mem* family
#include "libc.c"
i64 main() {
    u8 a[4];
    u8 b[4];
    a[0] = 1; b[0] = 2;
    if (memcmp(a, b, 0) != 0) { return 1; }
    if (memcpy(a, b, 0) != a) { return 2; }
    if (a[0] != 1) { return 3; }
    if (memset(a, 9, 0) != a) { return 4; }
    if (a[0] != 1) { return 5; }
    if (memmove(a, b, 0) != a) { return 6; }
    if (a[0] != 1) { return 7; }
    return 42;
}
