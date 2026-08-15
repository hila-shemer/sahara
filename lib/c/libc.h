/* libc.h - declarations for the SABI v0.2 libc surface (os/abi/
 * sabi-v0.md, Amendment v0.2 - DRAFT). This header and the amendment
 * move together: every public name here appears there with the same
 * signature rendering, and vice versa.
 *
 * The u8-pointer/u64 signatures are m1-subset renderings of the
 * classic void-pointer/size_t shapes (cc-m1 has neither); the
 * register-level ABI is what is frozen, and the cc-m2 retyping is
 * pre-authorized in the amendment.
 *
 * Programs normally get this via #include "libc.c" (one-TU
 * concatenation linkage, built by lib/c/ccbuild.sh); including this
 * header alone is fine for readability. Internals are __libc_* - m1
 * has no static, so the prefix is the containment; the whole
 * __libc_* space is reserved to the library.
 */
#ifndef LIBC_H
#define LIBC_H

/* the runtime surface - the library's entire world interface (the
 * wrappers in lang/cc/rt/sys.s, or whatever runtime is on the
 * assembler command line) */
extern i64 sys_write(i64 fd, u8 *buf, i64 len);
extern void sys_exit(i64 code);

/* mem* (v0.2 B.2) */
u8 *memcpy(u8 *dst, u8 *src, u64 n);
u8 *memmove(u8 *dst, u8 *src, u64 n);
u8 *memset(u8 *dst, u64 c, u64 n);
i64 memcmp(u8 *a, u8 *b, u64 n);

/* str* (v0.2 B.2; strcat/strncpy/strstr/strcasecmp deferred to the
 * DOOM-shim amendment - a name not in the amendment does not exist) */
u64 strlen(u8 *s);
i64 strcmp(u8 *a, u8 *b);
i64 strncmp(u8 *a, u8 *b, u64 n);
u8 *strcpy(u8 *dst, u8 *src);
u8 *strchr(u8 *s, u64 c);

/* allocator (v0.2 B.3): heap [_end rounded to 16, 0x0200_0000),
 * 16-aligned results, OOM = 0, corners pinned in the amendment */
u8 *malloc(u64 n);
void free(u8 *p);
u8 *realloc(u8 *p, u64 n);

/* conversions (v0.2 B.4): minimal digits out, strict parsing in;
 * buffer minimums incl NUL: 21 / 21 / 17 / 40 / 33 */
u64 u64_to_dec(u8 *buf, u64 v);
u64 i64_to_dec(u8 *buf, i64 v);
u64 u64_to_hex(u8 *buf, u64 v);
u64 u128_to_dec(u8 *buf, u128 v);
u64 u128_to_hex(u8 *buf, u128 v);
u64 dec_to_u64(u8 *s, u8 **end);
i64 dec_to_i64(u8 *s, u8 **end);
u128 dec_to_u128(u8 *s, u8 **end);
u64 hex_to_u64(u8 *s, u8 **end);
u128 hex_to_u128(u8 *s, u8 **end);

/* output (v0.2 B.5): fixed arity over sys_write(0, ...), the
 * syscall's return passed through. printf waits for varargs in the
 * compiler (cc-m3 as currently cut); no emulation here, by amendment
 * ban. */
i64 print_str(u8 *s);
i64 print_u64(u64 v);
i64 print_i64(i64 v);
i64 print_hex(u64 v);
i64 print_u128_hex(u128 v);

#endif
