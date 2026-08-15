// expect: 42
// strcpy copies through the NUL, returns dst, touches nothing past it
#include "libc.c"
i64 main() {
    u8 buf[16];
    u64 i = 0;
    while (i < 16) { buf[i] = 0x55; i = i + 1; }
    u8 *r = strcpy(buf, "hi there");
    if (r != buf) { return 1; }
    if (strlen(buf) != 8) { return 2; }
    if (memcmp(buf, "hi there", 9) != 0) { return 3; }  /* incl NUL */
    if (buf[9] != 0x55) { return 4; }
    strcpy(buf, "");
    if (buf[0] != 0) { return 5; }
    if (buf[1] != 'i') { return 6; }    /* only the NUL moved */
    return 42;
}
