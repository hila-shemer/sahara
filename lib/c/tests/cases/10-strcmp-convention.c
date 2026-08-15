// expect: 42
// oracle: no
// str[n]cmp raw difference values, incl NUL-vs-letter at unequal
// lengths - our convention, not the host's
#include "libc.c"
i64 main() {
    if (strcmp("a\xff", "a\x01") != 254) { return 1; }
    if (strcmp("a\x01", "a\xff") != -254) { return 2; }
    if (strcmp("ab", "abc") != 0 - 'c') { return 3; }
    if (strcmp("abc", "ab") != 'c') { return 4; }
    if (strncmp("a\xffz", "a\x01z", 2) != 254) { return 5; }
    return 42;
}
