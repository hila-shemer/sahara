// cc-error
// frame beyond 2^20 must be a loud compile error (cc-m1.md 11)
i64 main() { u8 buf[2000000]; buf[0] = (u8)1; return (i64)buf[0]; }
