/* alloc.c - malloc/free/realloc over [_end rounded to 16, 0x0200_0000)
 * per SABI v0.2 B.3. K&R-shaped: one address-ordered first-fit free
 * list, 16-byte headers, coalescing on free. The header is two u64s
 * at a 16-aligned address - [h] = block size incl header, [h+8] =
 * next free header (free blocks only) - kept as raw u64 addresses
 * rather than a struct: pointer members are 16 bytes in m1, which
 * would bloat the header to 32 for no benefit.
 *
 * State is ordinary bss globals; __libc_ is the containment (no
 * static in m1). Lazy init on first malloc: crt0 runs no
 * constructors, and bss-zero makes "0 = not ready" free.
 */

extern u8 _end;

u64 __libc_heap_base;   /* first byte of the arena, 16-aligned */
u64 __libc_heap_end;    /* the v0.2 ceiling: 0x0200_0000 */
u64 __libc_free_head;   /* address of first free header, 0 = none */
u64 __libc_heap_ready;

void __libc_heap_setup() {
    u64 base = ((u64)&_end + 15) & 0xFFFFFFFFFFFFFFF0;
    u64 end = 0x02000000;
    u64 *h = (u64 *)base;
    h[0] = end - base;      /* one block, the whole arena */
    h[1] = 0;
    __libc_heap_base = base;
    __libc_heap_end = end;
    __libc_free_head = base;
    __libc_heap_ready = 1;
}

u8 *malloc(u64 n) {
    if (n == 0) {
        return (u8 *)0;
    }
    if (__libc_heap_ready == 0) {
        __libc_heap_setup();
    }
    if (n > __libc_heap_end) {
        /* absurd size: also keeps n + 15 below from wrapping */
        return (u8 *)0;
    }
    u64 need = ((n + 15) & 0xFFFFFFFFFFFFFFF0) + 16;
    u64 prev = 0;
    u64 cur = __libc_free_head;
    while (cur != 0) {
        u64 *c = (u64 *)cur;
        if (c[0] >= need) {
            u64 rem = c[0] - need;
            if (rem >= 32) {
                /* carve from the front; the remainder stays free */
                u64 nf = cur + need;
                u64 *f = (u64 *)nf;
                f[0] = rem;
                f[1] = c[1];
                c[0] = need;
                if (prev == 0) { __libc_free_head = nf; }
                else { ((u64 *)prev)[1] = nf; }
            } else {
                /* remainder too small to be a block: give it all
                 * (a 16-byte sliver could never be allocated, only
                 * leak until its left neighbor is freed) */
                if (prev == 0) { __libc_free_head = c[1]; }
                else { ((u64 *)prev)[1] = c[1]; }
            }
            return (u8 *)(cur + 16);
        }
        prev = cur;
        cur = c[1];
    }
    return (u8 *)0;     /* OOM = 0, never a trap (v0.2 B.3) */
}

void free(u8 *p) {
    if (p == 0) {
        return;
    }
    u64 h = (u64)p - 16;
    u64 *hb = (u64 *)h;
    /* address-ordered insert... */
    u64 prev = 0;
    u64 cur = __libc_free_head;
    while (cur != 0 && cur < h) {
        prev = cur;
        cur = ((u64 *)cur)[1];
    }
    hb[1] = cur;
    if (prev == 0) { __libc_free_head = h; }
    else { ((u64 *)prev)[1] = h; }
    /* ...then coalesce: right neighbor first (keeps hb the survivor),
     * left neighbor second */
    if (cur != 0 && h + hb[0] == cur) {
        hb[0] = hb[0] + ((u64 *)cur)[0];
        hb[1] = ((u64 *)cur)[1];
    }
    if (prev != 0 && prev + ((u64 *)prev)[0] == h) {
        ((u64 *)prev)[0] = ((u64 *)prev)[0] + hb[0];
        ((u64 *)prev)[1] = hb[1];
    }
}

u8 *realloc(u8 *p, u64 n) {
    if (p == 0) {
        return malloc(n);
    }
    if (n == 0) {
        free(p);
        return (u8 *)0;
    }
    u64 h = (u64)p - 16;
    u64 *hb = (u64 *)h;
    if (n > __libc_heap_end) {
        return (u8 *)0;
    }
    u64 need = ((n + 15) & 0xFFFFFFFFFFFFFFF0) + 16;
    if (need <= hb[0]) {
        /* shrink or same: in place; return a big-enough tail */
        u64 rem = hb[0] - need;
        if (rem >= 32) {
            hb[0] = need;
            u64 t = h + need;
            ((u64 *)t)[0] = rem;
            free((u8 *)(t + 16));
        }
        return p;
    }
    /* grow = allocate-copy-free (the amendment's committed shape) */
    u8 *q = malloc(n);
    if (q == 0) {
        return (u8 *)0;
    }
    memcpy(q, p, hb[0] - 16);
    free(p);
    return q;
}
