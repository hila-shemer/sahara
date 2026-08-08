#include "mem.h"

#include "hostmem.h"
#include "rwc/status.h"

static uint64_t hash_page(uint64_t x)
{
    /* splitmix64 finisher: deterministic, good avalanche */
    x += 0x9e3779b97f4a7c15ull;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

void SeMem_init(SeMem *m, uint64_t ram_len)
{
    m->ram_len = ram_len;
    m->cap = 0;
    m->count = 0;
    m->keys = NULL;
    m->blocks = NULL;
}

bool SeMem_in_ram(const SeMem *m, se_u128 pa, unsigned size)
{
    if (pa >= (se_u128)m->ram_len)
        return false;
    return (se_u128)size <= (se_u128)m->ram_len - pa;
}

static void grow(SeMem *m)
{
    uint64_t ncap = m->cap ? m->cap * 2u : 64u;
    uint64_t *nk = se_host_alloc(ncap * sizeof *nk);
    uint8_t **nb = se_host_alloc(ncap * sizeof *nb);
    for (uint64_t i = 0; i < m->cap; i++) {
        if (!m->keys[i])
            continue;
        uint64_t j = hash_page(m->keys[i] - 1u) & (ncap - 1u);
        while (nk[j])
            j = (j + 1u) & (ncap - 1u);
        nk[j] = m->keys[i];
        nb[j] = m->blocks[i];
    }
    if (m->cap) {
        se_host_free(m->keys, m->cap * sizeof *m->keys);
        se_host_free(m->blocks, m->cap * sizeof *m->blocks);
    }
    m->cap = ncap;
    m->keys = nk;
    m->blocks = nb;
}

static uint8_t *lookup(const SeMem *m, uint64_t page_no)
{
    if (m->cap == 0)
        return NULL;
    uint64_t i = hash_page(page_no) & (m->cap - 1u);
    while (m->keys[i]) {
        if (m->keys[i] == page_no + 1u)
            return m->blocks[i];
        i = (i + 1u) & (m->cap - 1u);
    }
    return NULL;
}

static uint8_t *insert(SeMem *m, uint64_t page_no)
{
    if (m->cap == 0 || (m->count + 1u) * 10u >= m->cap * 7u)
        grow(m);
    uint64_t i = hash_page(page_no) & (m->cap - 1u);
    while (m->keys[i])
        i = (i + 1u) & (m->cap - 1u);
    uint8_t *blk = se_host_alloc(SE_PAGE_BYTES);
    m->keys[i] = page_no + 1u;
    m->blocks[i] = blk;
    m->count++;
    return blk;
}

/* Accesses must stay inside one 64 KB page (mem.h contract); pa may be
 * RAM or a memory-like device window, so the bound is 2^64, not
 * ram_len -- space classification is the caller's job (platform.h). */
static bool access_ok(se_u128 pa, unsigned size)
{
    if (se_hi64(pa) != 0u || size == 0u || size > 16u)
        return false;
    return (se_lo64(pa) & (SE_PAGE_BYTES - 1u)) + size <= SE_PAGE_BYTES;
}

se_u128 SeMem_read(SeMem *m, se_u128 pa, unsigned size)
{
    RWC_ASSERT(access_ok(pa, size));
    uint64_t addr = se_lo64(pa);
    const uint8_t *blk = lookup(m, addr >> SE_PAGE_SHIFT);
    if (!blk)
        return 0;
    uint32_t off = (uint32_t)(addr & (SE_PAGE_BYTES - 1u));
    se_u128 v = 0;
    for (unsigned i = 0; i < size; i++)
        v |= (se_u128)blk[off + i] << (8u * i);
    return v;
}

void SeMem_write(SeMem *m, se_u128 pa, unsigned size, se_u128 val)
{
    RWC_ASSERT(access_ok(pa, size));
    uint64_t addr = se_lo64(pa);
    uint64_t page_no = addr >> SE_PAGE_SHIFT;
    uint8_t *blk = lookup(m, page_no);
    if (!blk)
        blk = insert(m, page_no);
    uint32_t off = (uint32_t)(addr & (SE_PAGE_BYTES - 1u));
    for (unsigned i = 0; i < size; i++)
        blk[off + i] = (uint8_t)(val >> (8u * i));
}
