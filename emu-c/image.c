#include "image.h"

#include <stdio.h>

#include "hostmem.h"
#include "sha256.h"

#define IMG_MAGIC 0x3130474d49484153ull /* "SAHIMG01" little-endian */
#define IMG_HDR_BYTES 32u
#define IMG_SEG_BYTES 48u
/* The device table occupies [0x800, 0x1000) (PLATFORM-SPEC sections 1-2:
 * 2 KB at 0x0800); segments must not overlap it. */
#define DEVTAB_PA 0x800ull
#define DEVTAB_END 0x1000ull

static uint64_t get_u64(const uint8_t *p)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < 8u; i++)
        v |= (uint64_t)p[i] << (8u * i);
    return v;
}

static se_u128 get_u128(const uint8_t *p)
{
    se_u128 v = 0;
    for (unsigned i = 0; i < 16u; i++)
        v |= (se_u128)p[i] << (8u * i);
    return v;
}

/* Read the whole file into a fresh se_host_alloc buffer. On success
 * *buf_out and *len_out are set (len >= IMG_HDR_BYTES); on error nothing is
 * allocated. Either way the FILE is closed exactly once, here. */
static const char *slurp_image(const char *path, uint8_t **buf_out,
                               uint64_t *len_out)
{
    const char *err = NULL;
    uint8_t *buf = NULL;
    uint64_t flen = 0;
    FILE *f = fopen(path, "rb");
    if (!f)
        return "cannot open image file";
    if (fseek(f, 0, SEEK_END) != 0) {
        err = "cannot seek image file";
        goto out;
    }
    long endpos = ftell(f);
    if (endpos < 0 || fseek(f, 0, SEEK_SET) != 0) {
        err = "cannot size image file";
        goto out;
    }
    flen = (uint64_t)endpos;
    if (flen < IMG_HDR_BYTES) {
        err = "image too short for header";
        goto out;
    }
    buf = se_host_alloc(flen);
    if (fread(buf, 1u, flen, f) != flen) {
        se_host_free(buf, flen);
        buf = NULL;
        err = "short read of image file";
        goto out;
    }
    *buf_out = buf;
    *len_out = flen;
out:
    fclose(f);
    return err;
}

const char *se_image_load(SeMem *m, const char *path, se_u128 *entry_out,
                          uint8_t sha256_out[32])
{
    uint8_t *buf;
    uint64_t flen;
    const char *serr = slurp_image(path, &buf, &flen);
    if (serr)
        return serr;

    se_sha256(buf, flen, sha256_out);

    const char *err = NULL;
    if (get_u64(buf) != IMG_MAGIC) {
        err = "bad image magic";
        goto out;
    }
    se_u128 entry = get_u128(buf + 8u);
    uint64_t nsegs = get_u64(buf + 24u);
    if ((entry & 7u) != 0u) {
        err = "image entry not 8-aligned";
        goto out;
    }
    if (nsegs > (flen - IMG_HDR_BYTES) / IMG_SEG_BYTES) {
        err = "segment table exceeds file";
        goto out;
    }
    *entry_out = entry;

    for (uint64_t s = 0; s < nsegs; s++) {
        const uint8_t *d = buf + IMG_HDR_BYTES + s * IMG_SEG_BYTES;
        se_u128 load_pa = get_u128(d);
        uint64_t file_off = get_u64(d + 16u);
        uint64_t file_len = get_u64(d + 24u);
        uint64_t mem_len = get_u64(d + 32u);
        if (mem_len < file_len) {
            err = "segment mem_len < file_len";
            goto out;
        }
        if (file_off > flen || file_len > flen - file_off) {
            err = "segment file range exceeds file";
            goto out;
        }
        if (!SeMem_in_ram(m, load_pa, 1u) || mem_len == 0u ||
            (se_u128)mem_len > (se_u128)m->ram_len - load_pa) {
            err = "segment outside guest RAM";
            goto out;
        }
        se_u128 seg_end = load_pa + mem_len;
        if (load_pa < DEVTAB_END && seg_end > DEVTAB_PA) {
            err = "segment overlaps device table";
            goto out;
        }
        /* overlap with earlier segments (TOOLING-SPEC section 1) */
        for (uint64_t t = 0; t < s; t++) {
            const uint8_t *e = buf + IMG_HDR_BYTES + t * IMG_SEG_BYTES;
            se_u128 t_pa = get_u128(e);
            se_u128 t_end = t_pa + get_u64(e + 32u);
            if (load_pa < t_end && seg_end > t_pa) {
                err = "segments overlap";
                goto out;
            }
        }
        for (uint64_t i = 0; i < file_len; i++)
            SeMem_write(m, load_pa + i, 1u, buf[file_off + i]);
        /* [file_len, mem_len) is zero-filled: fresh RAM already reads
         * zero, and segment overlap is rejected above, so nothing can
         * have written there earlier. */
    }

out:
    se_host_free(buf, flen);
    return err;
}
