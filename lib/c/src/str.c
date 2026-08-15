/* str.c - strlen/strcmp/strncmp/strcpy/strchr per SABI v0.2 B.2.
 * The comparison functions share memcmp's difference convention.
 * strcat/strncpy/strstr/strcasecmp are deliberately absent - they
 * wait for the DOOM-shim amendment's measured symbol list.
 */

u64 strlen(u8 *s) {
    u64 n = 0;
    while (s[n]) {
        n = n + 1;
    }
    return n;
}

i64 strcmp(u8 *a, u8 *b) {
    u64 i = 0;
    while (1) {
        if (a[i] != b[i]) {
            return (i64)a[i] - (i64)b[i];
        }
        if (a[i] == 0) {
            return 0;
        }
        i = i + 1;
    }
    return 0;
}

i64 strncmp(u8 *a, u8 *b, u64 n) {
    u64 i = 0;
    while (i < n) {
        if (a[i] != b[i]) {
            return (i64)a[i] - (i64)b[i];
        }
        if (a[i] == 0) {
            return 0;
        }
        i = i + 1;
    }
    return 0;
}

u8 *strcpy(u8 *dst, u8 *src) {
    u64 i = 0;
    while (src[i]) {
        dst[i] = src[i];
        i = i + 1;
    }
    dst[i] = 0;
    return dst;
}

u8 *strchr(u8 *s, u64 c) {
    u64 ch = c & 0xff;
    u64 i = 0;
    while (1) {
        if (s[i] == ch) {
            return s + i;   /* c = 0 finds the terminating NUL */
        }
        if (s[i] == 0) {
            return (u8 *)0;
        }
        i = i + 1;
    }
    return (u8 *)0;
}
