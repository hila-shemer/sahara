/* mem.c - memcpy/memmove/memset/memcmp per SABI v0.2 B.2.
 * Byte loops on purpose: u8 work promotes to u64 (cc-m1 5.1) and
 * every operation stays canonical by construction. No word-at-a-time
 * cleverness until something measures the need.
 */

u8 *memcpy(u8 *dst, u8 *src, u64 n) {
    /* forward, ALWAYS - overlap is a deterministic forward copy,
     * defined and documented (v0.2 B.2). */
    u64 i = 0;
    while (i < n) {
        dst[i] = src[i];
        i = i + 1;
    }
    return dst;
}

u8 *memmove(u8 *dst, u8 *src, u64 n) {
    if (dst < src) {
        u64 i = 0;
        while (i < n) {
            dst[i] = src[i];
            i = i + 1;
        }
        return dst;
    }
    u64 j = n;
    while (j > 0) {
        j = j - 1;
        dst[j] = src[j];
    }
    return dst;
}

u8 *memset(u8 *dst, u64 c, u64 n) {
    u64 i = 0;
    while (i < n) {
        dst[i] = (u8)c;     /* c mod 256 */
        i = i + 1;
    }
    return dst;
}

i64 memcmp(u8 *a, u8 *b, u64 n) {
    /* returns the byte DIFFERENCE at the first mismatch, not just its
     * sign (v0.2 B.2) - deterministic, and portable callers compare
     * the sign only. */
    u64 i = 0;
    while (i < n) {
        if (a[i] != b[i]) {
            return (i64)a[i] - (i64)b[i];
        }
        i = i + 1;
    }
    return 0;
}
