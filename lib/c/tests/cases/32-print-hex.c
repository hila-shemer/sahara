// expect: 42
// oracle: no
// syscalls: 4
// capture: deadbeef 10000000000000abc\n
#include "libc.c"
i64 main() {
    if (print_hex(0xdeadbeef) != 8) { return 1; }
    if (print_str(" ") != 1) { return 2; }
    u128 v = ((u128)1 << 64) + 0xabc;
    if (print_u128_hex(v) != 17) { return 3; }
    if (print_str("\n") != 1) { return 4; }
    return 42;
}
