/* conv.c - number/text conversions per SABI v0.2 B.4. The u64
 * entries delegate to the u128 ones (one digit loop per direction,
 * not four): values below 2^64 divide identically at width 128, and
 * truncating a stepwise-wrapping accumulator to 64 bits equals
 * accumulating at 64 bits - mod arithmetic is a homomorphism, so the
 * wrap-on-overflow contract survives the delegation.
 *
 * The digit table is a string literal INSIDE each function: m1 has no
 * string-literal initializers for globals (rodata is reachable only
 * through literals in expressions) - recorded as cc-m2 friction.
 */

u64 u128_to_dec(u8 *buf, u128 v) {
    u8 tmp[40];
    u64 i = 0;
    if (v == 0) {
        tmp[0] = '0';
        i = 1;
    }
    while (v != 0) {
        tmp[i] = (u8)('0' + (u64)(v % 10));
        v = v / 10;
        i = i + 1;
    }
    u64 j = 0;
    while (j < i) {
        buf[j] = tmp[i - 1 - j];
        j = j + 1;
    }
    buf[i] = 0;
    return i;
}

u64 u128_to_hex(u8 *buf, u128 v) {
    u8 *digs = "0123456789abcdef";
    u8 tmp[32];
    u64 i = 0;
    if (v == 0) {
        tmp[0] = '0';
        i = 1;
    }
    while (v != 0) {
        tmp[i] = digs[(u64)(v & 15)];
        v = v >> 4;
        i = i + 1;
    }
    u64 j = 0;
    while (j < i) {
        buf[j] = tmp[i - 1 - j];
        j = j + 1;
    }
    buf[i] = 0;
    return i;
}

u64 u64_to_dec(u8 *buf, u64 v) {
    return u128_to_dec(buf, (u128)v);
}

u64 u64_to_hex(u8 *buf, u64 v) {
    return u128_to_hex(buf, (u128)v);
}

u64 i64_to_dec(u8 *buf, i64 v) {
    if (v < 0) {
        buf[0] = '-';
        /* 0 - (u64)v wraps correctly for i64 MIN too */
        return 1 + u64_to_dec(buf + 1, 0 - (u64)v);
    }
    return u64_to_dec(buf, (u64)v);
}

/* digit values, 99 = not a digit (sentinel > 15) */
u64 __libc_decval(u64 ch) {
    if (ch >= '0' && ch <= '9') { return ch - '0'; }
    return 99;
}

u64 __libc_hexval(u64 ch) {
    if (ch >= '0' && ch <= '9') { return ch - '0'; }
    if (ch >= 'a' && ch <= 'f') { return ch - 'a' + 10; }
    if (ch >= 'A' && ch <= 'F') { return ch - 'A' + 10; }
    return 99;
}

u128 dec_to_u128(u8 *s, u8 **end) {
    u128 v = 0;
    u8 *p = s;
    while (1) {
        u64 d = __libc_decval(*p);
        if (d == 99) { break; }
        v = v * 10 + d;
        p = p + 1;
    }
    if (end != 0) { *end = p; }
    return v;
}

u128 hex_to_u128(u8 *s, u8 **end) {
    u128 v = 0;
    u8 *p = s;
    while (1) {
        u64 d = __libc_hexval(*p);
        if (d == 99) { break; }
        v = v * 16 + d;
        p = p + 1;
    }
    if (end != 0) { *end = p; }
    return v;
}

u64 dec_to_u64(u8 *s, u8 **end) {
    return (u64)dec_to_u128(s, end);
}

u64 hex_to_u64(u8 *s, u8 **end) {
    return (u64)hex_to_u128(s, end);
}

i64 dec_to_i64(u8 *s, u8 **end) {
    u8 *p = s;
    u64 neg = 0;
    if (*p == '-') {
        neg = 1;
        p = p + 1;
    }
    u8 *q;
    u64 v = dec_to_u64(p, &q);
    if (q == p) {
        /* no digits: NOTHING consumed, not even the '-' (B.4) */
        if (end != 0) { *end = s; }
        return 0;
    }
    if (end != 0) { *end = q; }
    if (neg) { return (i64)(0 - v); }
    return (i64)v;
}
