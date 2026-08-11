// expect: 0x77
// oracle: no
// syscalls: 2
// capture: hi cc\n
// the one dedicated syscall test: SABI 3 mechanism end to end
extern i64 sys_write(i64 fd, u8 *buf, i64 len);
extern void sys_exit(i64 code);
i64 slen(u8 *s) { i64 n = 0; while (s[n]) n = n + 1; return n; }
i64 main() {
    u8 *msg = "hi cc\n";
    i64 wrote = sys_write(0, msg, slen(msg));
    sys_exit(0x70 + wrote - 6 + 7);
    return 0;
}
