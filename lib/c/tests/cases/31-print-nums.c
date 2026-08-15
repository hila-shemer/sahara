// expect: 42
// oracle: no
// syscalls: 4
// capture: 18446744073709551615|-42\n
#include "libc.c"
i64 main() {
    if (print_u64(0xFFFFFFFFFFFFFFFF) != 20) { return 1; }
    if (print_str("|") != 1) { return 2; }
    if (print_i64(-42) != 3) { return 3; }
    if (print_str("\n") != 1) { return 4; }
    return 42;
}
