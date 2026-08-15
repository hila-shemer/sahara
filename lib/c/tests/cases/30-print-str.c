// expect: 42
// oracle: no
// syscalls: 2
// capture: hello, libc\n
// print_str returns the syscall's answer (= length written); the
// empty string still costs a syscall and returns 0
#include "libc.c"
i64 main() {
    i64 r = print_str("hello, libc\n");
    if (r != 12) { return 1; }
    if (print_str("") != 0) { return 2; }
    return 42;
}
