/* Short-tier unit tests (run at build time; no argv, no data files):
 * u128 helpers incl. the manual 128x128->256 high halves, sparse memory,
 * and the MMU walk via SeCpu_translate. Expected MULH values computed
 * with Python bigints (see test/run_tests.py for the randomized CI
 * cross-check of the same code path through the emulator binary). */
#include <stdio.h>

#include <string.h>

#include "cpu.h"
#include "gen/sahara_isa.h"
#include "mem.h"
#include "rw/status.h"
#include "sha256.h"
#include "u128.h"

static void test_extend(void)
{
    RW_ASSERT(se_sext(0xFFu, 8u) == ~(se_u128)0);
    RW_ASSERT(se_sext(0x7Fu, 8u) == 0x7Fu);
    RW_ASSERT(se_zext(~(se_u128)0, 32u) == 0xFFFFFFFFu);
    RW_ASSERT(se_canon(0x80000000u, 32u) ==
              se_make128(0xFFFFFFFFFFFFFFFFull, 0xFFFFFFFF80000000ull));
    RW_ASSERT(se_sext(0, 128u) == 0u);
}

typedef struct MulVec {
    uint64_t a_hi, a_lo, b_hi, b_lo, h_hi, h_lo;
} MulVec;

static void test_mulh(void)
{
    static const MulVec vu[] = {
        {0x6513270e269e0d37ull, 0xf2a74de452e6b438ull,
         0xd23f0824128b2f33ull, 0x0c5c7fd0a6a3a450ull,
         0x530298f70f6563b7ull, 0x63b9715a38223acaull},
        {0x9531985d5d9dc9f8ull, 0x1818e811892f902bull,
         0x36f675cc81e74ef5ull, 0xe8e25d940ed90475ull,
         0x20081872f5541ff6ull, 0x158fdc07a531d044ull},
        {0x6b0d549b6f03675aull, 0x1600a35a099950d8ull,
         0x8d116ece1738f7d9ull, 0x3d9c172411e20b8full,
         0x3afda1d223422316ull, 0x73eb69d061615871ull},
    };
    static const MulVec vs[] = {
        {0x90c192cfd3ac94afull, 0x0f21ddb66cad4a26ull,
         0xa170b33839263059ull, 0xf28c105d1fb17c23ull,
         0x2917315406898035ull, 0x5617f59caba0229eull},
        {0x0fd630f1f29d0da9ull, 0x953f48f1a09f76b5ull,
         0x0cb1e29c658cda14ull, 0x95e60af593bd04cfull,
         0x00c90b67f2abbec8ull, 0xc7bb96a800b3b835ull},
        {0x8e81973e0becd7b0ull, 0x3898d190f9ebdaccull,
         0x6b4cb2424a23d596ull, 0x2217beaddbc496cbull,
         0xd06e29a88d1b3d7full, 0x5196d4f210da02e3ull},
    };
    for (unsigned i = 0; i < 3u; i++) {
        se_u128 h = se_mulhu128(se_make128(vu[i].a_hi, vu[i].a_lo),
                                se_make128(vu[i].b_hi, vu[i].b_lo));
        RW_ASSERT(h == se_make128(vu[i].h_hi, vu[i].h_lo));
    }
    for (unsigned i = 0; i < 3u; i++) {
        se_u128 h = se_mulhs128(se_make128(vs[i].a_hi, vs[i].a_lo),
                                se_make128(vs[i].b_hi, vs[i].b_lo));
        RW_ASSERT(h == se_make128(vs[i].h_hi, vs[i].h_lo));
    }
}

static void test_sparse_mem(void)
{
    SeMem m;
    SeMem_init(&m, 1ull << 32);
    RW_ASSERT(SeMem_read(&m, 0x123456u, 8u) == 0u); /* untouched: zero */
    SeMem_write(&m, 0x10000u - 8u, 8u, 0x1122334455667788ull);
    RW_ASSERT(SeMem_read(&m, 0x10000u - 8u, 8u) == 0x1122334455667788ull);
    RW_ASSERT(SeMem_read(&m, 0x10000u - 8u, 1u) == 0x88u); /* little-endian */
    se_u128 wide = se_make128(0xAABBCCDDEEFF0011ull, 0x2233445566778899ull);
    SeMem_write(&m, 0xFFFF0000u, 16u, wide);
    RW_ASSERT(SeMem_read(&m, 0xFFFF0000u, 16u) == wide);
    /* many pages: force hash growth */
    for (uint64_t i = 0; i < 200u; i++)
        SeMem_write(&m, i << SE_PAGE_SHIFT, 4u, (se_u128)(i + 1u));
    for (uint64_t i = 0; i < 200u; i++)
        RW_ASSERT(SeMem_read(&m, i << SE_PAGE_SHIFT, 4u) == (se_u128)(i + 1u));
    RW_ASSERT(!SeMem_in_ram(&m, (se_u128)1 << 32, 1u));
    RW_ASSERT(!SeMem_in_ram(&m, ((se_u128)1 << 32) - 4u, 8u));
}

/* Build a one-node page table mapping VPN 3 -> frame 0x50000 and check
 * the walk, permission causes, and malformation faults. */
static void test_mmu(void)
{
    SeMem m;
    SeMem_init(&m, 1ull << 24);
    SeTrace tr = { .f = NULL, .level = 0 };
    static SeCpu cpu; /* static: keep the short-test stack frame small */
    SeCpu_reset(&cpu, &m, &tr);

    se_u128 node = 0x10000u;
    SeMem_write(&m, node, 8u, 0u);            /* shift = 0 */
    SeMem_write(&m, node + 8u, 16u, 0u);      /* prefix = 0 */
    SeMem_write(&m, node + 24u, 16u,
                ~(se_u128)0xFFu);             /* prefix_mask: all but chunk 0 */
    /* leaf at index 3: frame 0x50000, R+W+X, supervisor-only */
    SeMem_write(&m, node + 64u + 3u * 16u, 16u,
                0x50000u | PTE_R | PTE_W | PTE_X | PTE_LEAF);
    /* leaf at index 4: read-only */
    SeMem_write(&m, node + 64u + 4u * 16u, 16u, 0x60000u | PTE_R | PTE_LEAF);

    cpu.sreg[SREG_PTBASE] = node;
    cpu.sreg[SREG_STATUS] |= STATUS_MMU_EN;

    SeXlate x = SeCpu_translate(&cpu, 0x30004u, SE_ACC_LOAD);
    RW_ASSERT(!x.fault && x.pa == 0x50004u);
    x = SeCpu_translate(&cpu, 0x30008u, SE_ACC_STORE);
    RW_ASSERT(!x.fault && x.pa == 0x50008u);
    x = SeCpu_translate(&cpu, 0x30000u, SE_ACC_FETCH);
    RW_ASSERT(!x.fault && x.pa == 0x50000u);

    x = SeCpu_translate(&cpu, 0x40000u, SE_ACC_STORE); /* read-only page */
    RW_ASSERT(x.fault && x.cause == CAUSE_PERM_STORE && x.baddr == 0x40000u);
    x = SeCpu_translate(&cpu, 0x50000u, SE_ACC_LOAD); /* invalid entry */
    RW_ASSERT(x.fault && x.cause == CAUSE_PF_LOAD);
    x = SeCpu_translate(&cpu, 0x1230000u, SE_ACC_LOAD); /* prefix mismatch */
    RW_ASSERT(x.fault && x.cause == CAUSE_PF_LOAD);

    /* user mode: U = 0 denies */
    cpu.sreg[SREG_STATUS] &= ~(se_u128)STATUS_S;
    x = SeCpu_translate(&cpu, 0x30000u, SE_ACC_LOAD);
    RW_ASSERT(x.fault && x.cause == CAUSE_PERM_LOAD);
    cpu.sreg[SREG_STATUS] |= STATUS_S;

    /* malformed: reserved leaf bits set */
    SeMem_write(&m, node + 64u + 5u * 16u, 16u,
                0x70000u | 0x40u | PTE_R | PTE_LEAF);
    x = SeCpu_translate(&cpu, 0x50000u | (5u << 16), SE_ACC_LOAD);
    RW_ASSERT(x.fault && x.cause == CAUSE_PF_LOAD);
    /* malformed: nonzero reserved header bytes */
    SeMem_write(&m, node + 48u, 8u, 1u);
    x = SeCpu_translate(&cpu, 0x30000u, SE_ACC_LOAD);
    RW_ASSERT(x.fault && x.cause == CAUSE_PF_LOAD);
    SeMem_write(&m, node + 48u, 8u, 0u);
    x = SeCpu_translate(&cpu, 0x30000u, SE_ACC_LOAD);
    RW_ASSERT(!x.fault);

    /* MMU off: identity */
    cpu.sreg[SREG_STATUS] &= ~(se_u128)STATUS_MMU_EN;
    x = SeCpu_translate(&cpu, 0x99990u, SE_ACC_STORE);
    RW_ASSERT(!x.fault && x.pa == 0x99990u);
}

/* FIPS 180-4 known-answer vectors: empty, one-block, and the two-block
 * 56-byte message (exercises the 128-byte padding tail). The image-level
 * check against devspec/trace.md TV-1's published digest lives in
 * test/run_tests.py. */
static void sha_vec(const char *msg, const char *want_hex)
{
    uint8_t d[32];
    se_sha256((const uint8_t *)msg, strlen(msg), d);
    char hex[65];
    for (unsigned i = 0; i < 32u; i++)
        snprintf(hex + 2u * i, 3u, "%02x", d[i]);
    RW_ASSERT(strcmp(hex, want_hex) == 0);
}

static void test_sha256(void)
{
    sha_vec("",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    sha_vec("abc",
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    sha_vec("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
}

int main(void)
{
    test_extend();
    test_mulh();
    test_sparse_mem();
    test_mmu();
    test_sha256();
    printf("test_core: OK\n");
    return 0;
}
