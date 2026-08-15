// expect: 42
// oracle: no
// Overlap is DEFINED here: memcpy is a forward copy always (v0.2
// B.2), so dst = s+1 over src = s propagates s[0] through the whole
// range. The host's memcpy calls this UB - hence no oracle leg.
#include "libc.c"
i64 main() {
    u8 s[16];
    u64 i = 0;
    while (i < 16) { s[i] = (u8)i; i = i + 1; }
    memcpy(s + 1, s, 15);
    i = 0;
    while (i < 16) {
        if (s[i] != 0) { return 1; }
        i = i + 1;
    }
    return 42;
}
