// expect: 42
// strchr: first hit, absent -> 0, c = 0 finds the NUL, c taken mod 256
#include "libc.c"
i64 main() {
    u8 *s = "abcabc";
    u8 *r = strchr(s, 'b');
    if (r != s + 1) { return 1; }
    if (strchr(s, 'z') != 0) { return 2; }
    r = strchr(s, 0);
    if (r != s + 6) { return 3; }
    if (strchr(s, 0x162) != s + 1) { return 4; }   /* mod 256 = 'b' */
    if (*strchr(s, 'c') != 'c') { return 5; }
    return 42;
}
