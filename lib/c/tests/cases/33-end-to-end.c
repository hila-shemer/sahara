// expect: 2425
// oracle: no
// syscalls: 2
// capture: ddbf6473c1880a5200012345\n
// The whole library in one image: compute a u128, malloc the string
// buffer, format hex, print it, parse it back, free - exit value is
// composed from the format length and the two write returns
// (24 * 100 + 24 + 1 = 2425).
#include "libc.c"
i64 main() {
    u128 v = (u128)0xFEEDFACE * (u128)0xDEADBEEF00000000 + 0x12345;
    u8 *buf = malloc(64);
    if (buf == 0) { return 1; }
    u64 n = u128_to_hex(buf, v);
    if (n != 24) { return 2; }
    if (strlen(buf) != 24) { return 3; }
    i64 w1 = print_str(buf);
    if (w1 != 24) { return 4; }
    i64 w2 = print_str("\n");
    if (w2 != 1) { return 5; }
    u8 *e = (u8 *)0;
    if (hex_to_u128(buf, &e) != v) { return 6; }
    if (e != buf + 24) { return 7; }
    free(buf);
    return (i64)n * 100 + w1 + w2;
}
