/* io.c - the fixed-arity print family per SABI v0.2 B.5: format into
 * a local buffer (conv.c), hand the bytes to sys_write(0, ...), and
 * pass the syscall's return through untouched - negated errno and
 * all. fd 0 always: capture buffer under the bare runtime, console
 * under an OS that adopts the library. No SYSCALL instruction lives
 * in the libc; sys_write/sys_exit are externs resolved by whatever
 * runtime is on the assembler command line.
 */

i64 print_str(u8 *s) {
    return sys_write(0, s, (i64)strlen(s));
}

i64 print_u64(u64 v) {
    u8 buf[24];
    u64 n = u64_to_dec(buf, v);
    return sys_write(0, buf, (i64)n);
}

i64 print_i64(i64 v) {
    u8 buf[24];
    u64 n = i64_to_dec(buf, v);
    return sys_write(0, buf, (i64)n);
}

i64 print_hex(u64 v) {
    u8 buf[24];
    u64 n = u64_to_hex(buf, v);
    return sys_write(0, buf, (i64)n);
}

i64 print_u128_hex(u128 v) {
    u8 buf[40];
    u64 n = u128_to_hex(buf, v);
    return sys_write(0, buf, (i64)n);
}
