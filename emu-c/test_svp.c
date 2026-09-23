/* Short-tier unit tests for SVP/2 (gui/svp.h): SHA-256 and HMAC-SHA256
 * known answers (FIPS 180-4, RFC 4231), the authentication messages and
 * the server's verdict on them, the token-file rules, fixed-message layout,
 * the incremental receiver under every split and under the server's
 * per-poll budget, the RAW/XRLE frame codec round trip across
 * successive frames, and rejection of every malformation the decoder
 * guards -- the socket shims above these are
 * too thin to unit-test; run-gui-tests.sh's serve/view leg covers the
 * assembled pipeline. */
#include <stdio.h>
#include <string.h>

#include "gui/hmac.h"
#include "gui/svp.h"
#include "hostmem.h"
#include "rwc/status.h"
#include "sha256.h"

enum { W = 64, H = 48 };

static void fill(uint8_t *fb, uint32_t seed)
{
    for (uint32_t i = 0; i < 4u * W * H; i++)
        fb[i] = (uint8_t)((i * 2654435761u) >> 24 ^ seed);
}

/* Feed msg into a fresh receiver n bytes at a time. */
static bool rx_one(SeSvpRx *r, const uint8_t *msg, uint64_t len, uint64_t step,
                   SeSvpMsg *out)
{
    uint64_t at = 0;
    while (at < len) {
        uint64_t room;
        uint8_t *dst = SeSvpRx_space(r, &room);
        uint64_t n = len - at < step ? len - at : step;
        RWC_ASSERT(n <= room);
        memcpy(dst, msg + at, n);
        SeSvpRx_commit(r, n);
        at += n;
        if (at < len)
            RWC_ASSERT(!SeSvpRx_next(r, out)); /* never early */
    }
    return SeSvpRx_next(r, out);
}

/* ------------------------------------------------- hashing and HMAC */

static uint32_t unhex(const char *hex, uint8_t *out)
{
    uint32_t n = 0;
    for (; hex[0] && hex[1]; hex += 2) {
        unsigned v;
        RWC_ASSERT(sscanf(hex, "%2x", &v) == 1);
        out[n++] = (uint8_t)v;
    }
    return n;
}

static void digest_is(const uint8_t *d, uint32_t n, const char *want_hex)
{
    uint8_t want[64];
    RWC_ASSERT(unhex(want_hex, want) == n);
    RWC_ASSERT(memcmp(d, want, n) == 0); /* a test: timing is moot */
}

/* FIPS 180-4 / NIST CSVS known answers for the core's SHA-256, which
 * HMAC stands on: empty, one block, the 448-bit two-block message,
 * the 896-bit message, and one million 'a'. */
static void test_sha256_vectors(void)
{
    uint8_t d[32];
    se_sha256((const uint8_t *)"", 0u, d);
    digest_is(d, 32u,
              "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    se_sha256((const uint8_t *)"abc", 3u, d);
    digest_is(d, 32u,
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    const char *m448 = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    se_sha256((const uint8_t *)m448, strlen(m448), d);
    digest_is(d, 32u,
              "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
    const char *m896 = "abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmn"
                       "hijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu";
    se_sha256((const uint8_t *)m896, strlen(m896), d);
    digest_is(d, 32u,
              "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1");
    uint8_t *mil = se_host_alloc(1000000u);
    memset(mil, 'a', 1000000u);
    se_sha256(mil, 1000000u, d);
    digest_is(d, 32u,
              "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
    se_host_free(mil, 1000000u);
}

/* RFC 4231 section 4, all seven HMAC-SHA-256 test cases: short keys,
 * a key shorter than the output, 0xaa/0xdd fill, a 25-byte key, the
 * truncated case 5 (first 128 bits), and the 131-byte keys of cases 6
 * and 7 that must be hashed down first (RFC 2104). */
static void test_hmac_vectors(void)
{
    static const struct {
        const char *key, *data, *mac;
        bool data_is_text;
    } tc[] = {
        { "0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b", "Hi There",
          "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7",
          true },
        { "4a656665", "what do ya want for nothing?",
          "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843",
          true },
        { "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "dddddddddddddddddddddddddddddddddddddddddddddddddd"
          "dddddddddddddddddddddddddddddddddddddddddddddddddd",
          "773ea91e36800e46854db8ebd09181a72959098b3ef8c122d9635514ced565fe",
          false },
        { "0102030405060708090a0b0c0d0e0f10111213141516171819",
          "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
          "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
          "82558a389a443c0ea4cc819899f2083a85f0faa3e578f8077a2e3ff46729665b",
          false },
        { "0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c", "Test With Truncation",
          "a3b6167473100ee06e0c796c2955552b", true },
        { NULL, "Test Using Larger Than Block-Size Key - Hash Key First",
          "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54",
          true },
        { NULL,
          "This is a test using a larger than block-size key and a larger "
          "than block-size data. The key needs to be hashed before being "
          "used by the HMAC algorithm.",
          "9b09ffa71b942fcb27635fbcd5b0e944bfdc63644f0713938a7f51535c3a35e2",
          true },
    };
    uint8_t aa131[131];
    memset(aa131, 0xaa, sizeof aa131);
    for (unsigned i = 0; i < sizeof tc / sizeof tc[0]; i++) {
        uint8_t key[64], data[256], want[32], out[32];
        const uint8_t *k = aa131;
        uint32_t klen = sizeof aa131;
        if (tc[i].key) {
            klen = unhex(tc[i].key, key);
            k = key;
        }
        uint32_t dlen;
        if (tc[i].data_is_text) {
            dlen = (uint32_t)strlen(tc[i].data);
            memcpy(data, tc[i].data, dlen);
        } else {
            dlen = unhex(tc[i].data, data);
        }
        uint32_t wlen = unhex(tc[i].mac, want);
        SeHmac_sha256(k, klen, data, dlen, out);
        RWC_ASSERT(memcmp(out, want, wlen) == 0);
    }
    /* Controls: a one-bit change of key or data changes the MAC. */
    uint8_t a[32], b[32];
    SeHmac_sha256((const uint8_t *)"Jefe", 4u, (const uint8_t *)"x", 1u, a);
    SeHmac_sha256((const uint8_t *)"Jeff", 4u, (const uint8_t *)"x", 1u, b);
    RWC_ASSERT(memcmp(a, b, 32u) != 0);
    SeHmac_sha256((const uint8_t *)"Jefe", 4u, (const uint8_t *)"y", 1u, b);
    RWC_ASSERT(memcmp(a, b, 32u) != 0);
}

static void test_ct_equal(void)
{
    uint8_t a[32], b[32];
    for (unsigned i = 0; i < 32u; i++)
        a[i] = b[i] = (uint8_t)(i * 37u + 1u);
    RWC_ASSERT(SeHmac_equal(a, b, 32u));
    RWC_ASSERT(SeHmac_equal(a, b, 0u)); /* nothing to differ */
    /* Every position, every bit: one flipped bit anywhere is unequal
     * (an early-exit or partial compare fails some of these). */
    for (unsigned i = 0; i < 32u; i++)
        for (unsigned bit = 0; bit < 8u; bit++) {
            b[i] ^= (uint8_t)(1u << bit);
            RWC_ASSERT(!SeHmac_equal(a, b, 32u));
            b[i] ^= (uint8_t)(1u << bit);
        }
    RWC_ASSERT(SeHmac_equal(a, b, 32u));
}

/* ------------------------------------------------------ authentication */

static const uint8_t TOKEN[] = "0123456789abcdefghij0123456789ABCDEFGHIJ+/w=";
enum { TOKEN_LEN = sizeof TOKEN - 1u };

static void test_auth_messages(void)
{
    static uint8_t rxbuf[256];
    SeSvpRx r;
    SeSvpMsg m;
    uint8_t b[128], nonce[SE_SVP_NONCE_BYTES], got[SE_SVP_NONCE_BYTES];
    for (unsigned i = 0; i < sizeof nonce; i++)
        nonce[i] = (uint8_t)(0xA5u ^ (i * 29u));

    /* CHALLENGE round trip, under ragged splits. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint32_t n = SeSvp_challenge(b, nonce);
    RWC_ASSERT(n == SE_SVP_HDR_BYTES + 4u + SE_SVP_NONCE_BYTES);
    RWC_ASSERT(b[0] == SE_SVP_CHALLENGE && b[4] == 36u && b[8] == 2u);
    RWC_ASSERT(rx_one(&r, b, n, 7u, &m));
    RWC_ASSERT(SeSvp_parse_challenge(&m, got));
    RWC_ASSERT(memcmp(got, nonce, sizeof nonce) == 0);
    /* Malformed CHALLENGEs: another version, short, long, wrong type,
     * and an SVP/1 server's HELLO in its place. */
    uint8_t c[64];
    memcpy(c, b, n);
    c[8] = 1u;
    SeSvpMsg bad = { SE_SVP_CHALLENGE, c + SE_SVP_HDR_BYTES, 36u };
    RWC_ASSERT(!SeSvp_parse_challenge(&bad, got));
    c[8] = 2u;
    RWC_ASSERT(SeSvp_parse_challenge(&bad, got)); /* control */
    bad.len = 35u;
    RWC_ASSERT(!SeSvp_parse_challenge(&bad, got));
    bad.len = 37u;
    RWC_ASSERT(!SeSvp_parse_challenge(&bad, got));
    bad.len = 36u;
    bad.type = SE_SVP_AUTH;
    RWC_ASSERT(!SeSvp_parse_challenge(&bad, got));
    uint8_t h[32];
    RWC_ASSERT(SeSvp_hello(h, 640u, 480u) == 20u);
    SeSvpMsg hello = { SE_SVP_HELLO, h + SE_SVP_HDR_BYTES, 12u };
    RWC_ASSERT(!SeSvp_parse_challenge(&hello, got));

    /* AUTH: the right answer passes, through the receiver. */
    n = SeSvp_auth(b, TOKEN, TOKEN_LEN, nonce);
    RWC_ASSERT(n == SE_SVP_HDR_BYTES + SE_SVP_MAC_BYTES && b[0] == SE_SVP_AUTH);
    RWC_ASSERT(rx_one(&r, b, n, 3u, &m));
    RWC_ASSERT(SeSvp_auth_ok(&m, TOKEN, TOKEN_LEN, nonce));
    /* The MAC is the documented one: HMAC(token, "SVP/2 AUTH" || nonce),
     * so another implementation (the test gate's Python) can answer. */
    uint8_t in[10 + SE_SVP_NONCE_BYTES], mac[32];
    memcpy(in, "SVP/2 AUTH", 10u);
    memcpy(in + 10u, nonce, sizeof nonce);
    SeHmac_sha256(TOKEN, TOKEN_LEN, in, sizeof in, mac);
    RWC_ASSERT(memcmp(b + SE_SVP_HDR_BYTES, mac, 32u) == 0);
    /* The token itself is not on the wire. */
    for (uint32_t i = 0; i + 8u <= n; i++)
        RWC_ASSERT(memcmp(b + i, TOKEN, 8u) != 0);

    /* Wrong token, wrong nonce (a replayed answer), any flipped byte. */
    uint8_t other[TOKEN_LEN];
    memcpy(other, TOKEN, TOKEN_LEN);
    other[TOKEN_LEN - 1u] ^= 1u;
    RWC_ASSERT(!SeSvp_auth_ok(&m, other, TOKEN_LEN, nonce));
    RWC_ASSERT(!SeSvp_auth_ok(&m, TOKEN, TOKEN_LEN - 1u, nonce));
    uint8_t nonce2[SE_SVP_NONCE_BYTES];
    memcpy(nonce2, nonce, sizeof nonce);
    nonce2[31] ^= 0x80u;
    RWC_ASSERT(!SeSvp_auth_ok(&m, TOKEN, TOKEN_LEN, nonce2));
    uint8_t a[SE_SVP_HDR_BYTES + SE_SVP_MAC_BYTES + 1u];
    memcpy(a, b, n);
    SeSvpMsg am = { SE_SVP_AUTH, a + SE_SVP_HDR_BYTES, SE_SVP_MAC_BYTES };
    RWC_ASSERT(SeSvp_auth_ok(&am, TOKEN, TOKEN_LEN, nonce)); /* control */
    for (unsigned i = 0; i < SE_SVP_MAC_BYTES; i++) {
        a[SE_SVP_HDR_BYTES + i] ^= 0x01u;
        RWC_ASSERT(!SeSvp_auth_ok(&am, TOKEN, TOKEN_LEN, nonce));
        a[SE_SVP_HDR_BYTES + i] ^= 0x01u;
    }
    /* Malformed AUTH: short, long (the right MAC plus a byte), wrong
     * type carrying the right MAC, and an empty message. */
    am.len = SE_SVP_MAC_BYTES - 1u;
    RWC_ASSERT(!SeSvp_auth_ok(&am, TOKEN, TOKEN_LEN, nonce));
    am.len = SE_SVP_MAC_BYTES + 1u;
    RWC_ASSERT(!SeSvp_auth_ok(&am, TOKEN, TOKEN_LEN, nonce));
    am.len = SE_SVP_MAC_BYTES;
    am.type = SE_SVP_KEY;
    RWC_ASSERT(!SeSvp_auth_ok(&am, TOKEN, TOKEN_LEN, nonce));
    SeSvpMsg empty = { SE_SVP_AUTH, a, 0u };
    RWC_ASSERT(!SeSvp_auth_ok(&empty, TOKEN, TOKEN_LEN, nonce));
    /* A first message that is input, not AUTH, is a refusal. */
    n = SeSvp_key(b, 4u, true, false);
    RWC_ASSERT(rx_one(&r, b, n, 16u, &m));
    RWC_ASSERT(!SeSvp_auth_ok(&m, TOKEN, TOKEN_LEN, nonce));
    /* A garbage header in the server's 256-byte pending buffer is bad,
     * which the server also treats as a refusal. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint8_t g[8] = { SE_SVP_AUTH, 0, 0, 0, 0x00, 0x10, 0, 0 };
    RWC_ASSERT(!rx_one(&r, g, 8u, 8u, &m) && r.bad);
}

static void test_token_rules(void)
{
    uint32_t tl = 0;
    /* `head -c 32 /dev/urandom | base64 > f`: 44 characters + newline. */
    const char *f = "q1U0bG1jQ2V0dGhpc2lzbm90cmFuZG9tYXRhbGwxMjM=\n";
    RWC_ASSERT(SeSvp_token_trim((const uint8_t *)f, strlen(f), &tl));
    RWC_ASSERT(tl == 44u);
    const char *crlf = "0123456789abcdef \t\r\n\n";
    RWC_ASSERT(SeSvp_token_trim((const uint8_t *)crlf, strlen(crlf), &tl));
    RWC_ASSERT(tl == 16u);
    RWC_ASSERT(!SeSvp_token_trim((const uint8_t *)"", 0u, &tl));
    RWC_ASSERT(!SeSvp_token_trim((const uint8_t *)"\n\n", 2u, &tl));
    RWC_ASSERT(!SeSvp_token_trim((const uint8_t *)"0123456789abcde\n", 16u,
                                 &tl)); /* 15 after trimming */
    static uint8_t big[SE_SVP_TOKEN_MAX + 2u];
    memset(big, 'x', sizeof big);
    RWC_ASSERT(SeSvp_token_trim(big, SE_SVP_TOKEN_MAX, &tl));
    RWC_ASSERT(tl == SE_SVP_TOKEN_MAX);
    RWC_ASSERT(!SeSvp_token_trim(big, SE_SVP_TOKEN_MAX + 1u, &tl));
    big[5] = 0u;
    RWC_ASSERT(!SeSvp_token_trim(big, 32u, &tl)); /* NUL inside */
    /* Leading whitespace is part of the token (only the tail is the
     * editor's or base64's newline). */
    RWC_ASSERT(SeSvp_token_trim((const uint8_t *)" 0123456789abcdef", 17u,
                                &tl) && tl == 17u);

    /* Permissions: mode bits as st_mode carries them. */
    RWC_ASSERT(SeSvp_token_perm(true, 0100600u, 1000u, 1000u) ==
               SE_SVP_TOKEN_PERM_OK);
    RWC_ASSERT(SeSvp_token_perm(true, 0100400u, 1000u, 1000u) ==
               SE_SVP_TOKEN_PERM_OK);
    RWC_ASSERT(SeSvp_token_perm(true, 0100700u, 1000u, 1000u) ==
               SE_SVP_TOKEN_PERM_OK);
    RWC_ASSERT(SeSvp_token_perm(true, 0100644u, 1000u, 1000u) ==
               SE_SVP_TOKEN_TOO_OPEN);
    RWC_ASSERT(SeSvp_token_perm(true, 0100640u, 1000u, 1000u) ==
               SE_SVP_TOKEN_TOO_OPEN);
    RWC_ASSERT(SeSvp_token_perm(true, 0100604u, 1000u, 1000u) ==
               SE_SVP_TOKEN_TOO_OPEN);
    RWC_ASSERT(SeSvp_token_perm(true, 0100601u, 1000u, 1000u) ==
               SE_SVP_TOKEN_TOO_OPEN);
    RWC_ASSERT(SeSvp_token_perm(true, 0100600u, 0u, 1000u) ==
               SE_SVP_TOKEN_WRONG_OWNER);
    RWC_ASSERT(SeSvp_token_perm(false, 0020600u, 1000u, 1000u) ==
               SE_SVP_TOKEN_NOT_REGULAR);
}

static void test_fixed_messages(void)
{
    static uint8_t rxbuf[4096];
    SeSvpRx r;
    SeSvpMsg m;
    uint8_t b[64];

    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint32_t n = SeSvp_hello(b, 640u, 480u);
    RWC_ASSERT(n == 20u && b[0] == SE_SVP_HELLO && b[4] == 12u);
    RWC_ASSERT(rx_one(&r, b, n, 1u, &m));
    uint32_t w, h;
    RWC_ASSERT(SeSvp_parse_hello(&m, &w, &h) && w == 640u && h == 480u);

    n = SeSvp_key(b, 0x04u, true, false);
    RWC_ASSERT(rx_one(&r, b, n, 3u, &m));
    uint32_t usage;
    bool press, repeat;
    RWC_ASSERT(SeSvp_parse_key(&m, &usage, &press, &repeat));
    RWC_ASSERT(usage == 0x04u && press && !repeat);
    RWC_ASSERT(!SeSvp_parse_mouse(&m, &(int32_t){0}, &(int32_t){0},
                                  &(uint8_t){0})); /* type-checked */

    n = SeSvp_mouse(b, -5, 700, 0xFFu);
    RWC_ASSERT(rx_one(&r, b, n, 5u, &m));
    int32_t x, y;
    uint8_t btn;
    RWC_ASSERT(SeSvp_parse_mouse(&m, &x, &y, &btn));
    RWC_ASSERT(x == -5 && y == 700 && btn == 7u); /* mask to 3 bits */

    n = SeSvp_ping(b, SE_SVP_PING, 0x1122334455667788ull);
    RWC_ASSERT(rx_one(&r, b, n, 8u, &m));
    uint64_t tok;
    RWC_ASSERT(SeSvp_parse_ping(&m, &tok) && tok == 0x1122334455667788ull);

    n = SeSvp_empty(b, SE_SVP_CLOSE);
    RWC_ASSERT(n == 8u && rx_one(&r, b, n, 2u, &m));
    RWC_ASSERT(m.type == SE_SVP_CLOSE && m.len == 0u);

    /* Two messages in one push come out in order. */
    n = SeSvp_empty(b, SE_SVP_FOCUSLOST);
    n += SeSvp_empty(b + n, SE_SVP_BUSY);
    uint64_t room;
    uint8_t *dst = SeSvpRx_space(&r, &room);
    memcpy(dst, b, n);
    SeSvpRx_commit(&r, n);
    RWC_ASSERT(SeSvpRx_next(&r, &m) && m.type == SE_SVP_FOCUSLOST);
    RWC_ASSERT(SeSvpRx_next(&r, &m) && m.type == SE_SVP_BUSY);
    RWC_ASSERT(!SeSvpRx_next(&r, &m));
}

static void test_rx_rejects(void)
{
    static uint8_t rxbuf[256];
    SeSvpRx r;
    SeSvpMsg m;
    uint8_t b[16] = { SE_SVP_KEY, 1, 0, 0, 0, 0, 0, 0 }; /* nonzero pad */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    RWC_ASSERT(!rx_one(&r, b, 8u, 8u, &m) && r.bad);
    /* Sticky: a good message after garbage is not parsed. */
    uint32_t n = SeSvp_empty(b, SE_SVP_CLOSE);
    uint64_t room;
    uint8_t *dst = SeSvpRx_space(&r, &room);
    memcpy(dst, b, n);
    SeSvpRx_commit(&r, n);
    RWC_ASSERT(!SeSvpRx_next(&r, &m));

    /* Oversize for this buffer: a server's input buffer refuses a
     * frame-sized message instead of waiting forever. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint8_t big[8] = { SE_SVP_FRAME, 0, 0, 0, 0x00, 0x10, 0, 0 }; /* 4 KB */
    RWC_ASSERT(!rx_one(&r, big, 8u, 8u, &m) && r.bad);

    /* Wrong payload sizes fail the typed parsers. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint8_t shortkey[12] = { SE_SVP_KEY, 0, 0, 0, 4, 0, 0, 0 };
    RWC_ASSERT(rx_one(&r, shortkey, 12u, 12u, &m));
    RWC_ASSERT(!SeSvp_parse_key(&m, &(uint32_t){0}, &(bool){0},
                                &(bool){0}));
    uint8_t hello_v[20];
    RWC_ASSERT(SeSvp_hello(hello_v, 640u, 480u) == 20u);
    hello_v[8] = 1u; /* an SVP/1 HELLO: no longer ours */
    RWC_ASSERT(rx_one(&r, hello_v, 20u, 20u, &m));
    RWC_ASSERT(!SeSvp_parse_hello(&m, &(uint32_t){0}, &(uint32_t){0}));
    hello_v[8] = 3u; /* nor a newer one */
    RWC_ASSERT(rx_one(&r, hello_v, 20u, 20u, &m));
    RWC_ASSERT(!SeSvp_parse_hello(&m, &(uint32_t){0}, &(uint32_t){0}));
}

/* The server's per-poll input budget (gui/be_svp.c) against a long
 * stream of small messages: a mirror of SeLiveBe_poll's loop, with the
 * socket played by a byte array that hands out ragged recv-sized
 * pieces. Every message must come out once, in order, no poll may
 * handle more than the budget, and SeSvpRx_ready must say "don't
 * sleep" exactly when a poll stopped on its budget with a whole
 * message still buffered. */
enum { STREAM_MSGS = 20000, POLL_BUDGET = 256, SERVER_RX = 4096 };

static void test_budgeted_stream(void)
{
    uint64_t total = (uint64_t)STREAM_MSGS * 16u;
    uint8_t *wire = se_host_alloc(total);
    uint64_t wlen = 0;
    for (uint32_t i = 0; i < STREAM_MSGS; i++)
        wlen += SeSvp_key(wire + wlen, i, (i & 1u) != 0u, false);
    RWC_ASSERT(wlen == total);

    static uint8_t rxbuf[SERVER_RX];
    SeSvpRx r;
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint64_t sent = 0;     /* wire bytes the "socket" has handed out */
    uint32_t next_usage = 0, polls = 0, piece = 0;
    while (next_usage < STREAM_MSGS) {
        RWC_ASSERT(polls < 4u * STREAM_MSGS / POLL_BUDGET + 16u);
        polls++;
        uint32_t budget = POLL_BUDGET;
        bool socket_empty = false;
        for (;;) {
            SeSvpMsg m;
            while (budget > 0u && SeSvpRx_next(&r, &m)) {
                uint32_t usage;
                bool press, repeat;
                RWC_ASSERT(SeSvp_parse_key(&m, &usage, &press, &repeat));
                RWC_ASSERT(usage == next_usage);
                RWC_ASSERT(press == ((usage & 1u) != 0u) && !repeat);
                next_usage++;
                budget--;
            }
            RWC_ASSERT(!r.bad);
            if (budget == 0u)
                break;
            uint64_t room;
            uint8_t *dst = SeSvpRx_space(&r, &room);
            /* Ragged pieces, 1..4999 bytes, some of them empty-socket
             * "EAGAIN" turns so a poll can also end short of budget. */
            uint64_t want = 1u + (uint64_t)(piece++ * 7919u) % 4999u;
            if (sent == wlen || piece % 13u == 0u) {
                socket_empty = true;
                break;
            }
            if (want > room)
                want = room;
            if (want > wlen - sent)
                want = wlen - sent;
            memcpy(dst, wire + sent, want);
            SeSvpRx_commit(&r, want);
            sent += want;
        }
        if (socket_empty)
            RWC_ASSERT(!SeSvpRx_ready(&r)); /* drained what was here */
    }
    RWC_ASSERT(next_usage == STREAM_MSGS && sent == wlen);
    RWC_ASSERT(polls >= STREAM_MSGS / POLL_BUDGET); /* budget held */
    RWC_ASSERT(!SeSvpRx_ready(&r));
    se_host_free(wire, total);

    /* Budget stop with a whole message buffered: ready, no socket. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint64_t room;
    uint8_t *dst = SeSvpRx_space(&r, &room);
    uint32_t n = SeSvp_key(dst, 7u, true, false);
    n += SeSvp_key(dst + n, 8u, true, false);
    SeSvpRx_commit(&r, n - 3u); /* one whole, one partial */
    RWC_ASSERT(SeSvpRx_ready(&r));
    SeSvpMsg m;
    RWC_ASSERT(SeSvpRx_next(&r, &m));
    RWC_ASSERT(!SeSvpRx_ready(&r)); /* partial: needs the socket */
    SeSvpRx_commit(&r, 3u);
    RWC_ASSERT(SeSvpRx_ready(&r));
    RWC_ASSERT(SeSvpRx_next(&r, &m) && !SeSvpRx_ready(&r));

    /* A malformed header is ready (the next poll must see it and drop
     * the viewer), and after SeSvpRx_next reports it, quiet. */
    dst = SeSvpRx_space(&r, &room);
    memset(dst, 0, 8u);
    dst[0] = SE_SVP_KEY;
    dst[2] = 1u;
    SeSvpRx_commit(&r, 8u);
    RWC_ASSERT(SeSvpRx_ready(&r));
    RWC_ASSERT(!SeSvpRx_next(&r, &m) && r.bad && !SeSvpRx_ready(&r));
}

/* The input token bucket: burst first, then the refill rate and no
 * more, however often it is polled -- the per-poll budget alone let a
 * flooding viewer be served as fast as the server loops. */
static void test_rate(void)
{
    SeSvpRate q;
    SeSvpRate_reset(&q, 256u, 1000u, 5000u);
    RWC_ASSERT(SeSvpRate_refill(&q, 5000u) == 256u);
    SeSvpRate_spend(&q, 256u);
    RWC_ASSERT(SeSvpRate_refill(&q, 5000u) == 0u);
    RWC_ASSERT(SeSvpRate_wait_ms(&q) == 1u);

    /* A tight poll loop over 2 s of clock, 0.1 ms per poll modelled as
     * every millisecond polled ten times, takes 2000 tokens. */
    uint64_t taken = 0;
    for (uint64_t ms = 5000u; ms < 7000u; ms++)
        for (unsigned i = 0; i < 10u; i++) {
            uint32_t n = SeSvpRate_refill(&q, ms);
            SeSvpRate_spend(&q, n);
            taken += n;
        }
    RWC_ASSERT(taken == 1999u); /* ms 5000 adds none, 5001..6999 add */

    /* An idle stretch refills to the burst and no further. */
    RWC_ASSERT(SeSvpRate_refill(&q, 60000u) == 256u);
    RWC_ASSERT(SeSvpRate_wait_ms(&q) == 0u);
    /* A clock that steps back changes nothing. */
    RWC_ASSERT(SeSvpRate_refill(&q, 10u) == 256u);

    /* A fractional rate: 3 tokens a second is one per 334 ms. */
    SeSvpRate_reset(&q, 1u, 3u, 0u);
    SeSvpRate_spend(&q, SeSvpRate_refill(&q, 0u));
    RWC_ASSERT(SeSvpRate_wait_ms(&q) == 334u);
    RWC_ASSERT(SeSvpRate_refill(&q, 333u) == 0u);
    RWC_ASSERT(SeSvpRate_refill(&q, 334u) == 1u);

    /* Huge values do not overflow: a full bucket after a huge gap. */
    SeSvpRate_reset(&q, UINT32_MAX, UINT32_MAX, 0u);
    SeSvpRate_spend(&q, SeSvpRate_refill(&q, 0u));
    RWC_ASSERT(SeSvpRate_refill(&q, UINT64_MAX) == UINT32_MAX);
}

static void test_frame_codec(void)
{
    uint64_t max = SeSvp_frame_msg_max(W, H);
    uint8_t *msg = se_host_alloc(max);
    uint8_t *rxbuf = se_host_alloc(max + 64u);
    uint32_t *prev = se_host_alloc(4u * W * H);
    static uint8_t cur[4 * W * H], fb[4 * W * H];
    SeSvpEnc e;
    SeSvpRx r;
    SeSvpMsg m;
    uint32_t seq;
    SeSvpEnc_reset(&e, prev, (uint64_t)W * H);
    SeSvpRx_reset(&r, rxbuf, max + 64u);
    memset(fb, 0, sizeof fb);

    /* Frame 0: noise, so XRLE is larger than RAW and RAW is chosen. */
    fill(cur, 0x5Au);
    uint64_t n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(msg[SE_SVP_HDR_BYTES + 4u] == SE_SVP_RAW);
    RWC_ASSERT(rx_one(&r, msg, n, 997u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq) && seq == 0u);
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Frame 1: one "glyph" changes -- XRLE, tiny, exact. */
    for (uint32_t y = 10; y < 26; y++)
        for (uint32_t x = 20; x < 28; x++)
            cur[4u * (y * W + x)] ^= 0xFFu;
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(msg[SE_SVP_HDR_BYTES + 4u] == SE_SVP_XRLE);
    RWC_ASSERT(n < 16u * 8u * 12u + 64u); /* 16 runs of 8 words */
    RWC_ASSERT(rx_one(&r, msg, n, 1u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq) && seq == 1u);
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Frame 2: identical -- one all-zero run. */
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(n == SE_SVP_HDR_BYTES + 16u + 8u);
    RWC_ASSERT(rx_one(&r, msg, n, 4096u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq) && seq == 2u);
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Frame 3: last word only, then first word only (run edges). */
    cur[4u * W * H - 1u] ^= 1u;
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(rx_one(&r, msg, n, 64u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq));
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);
    cur[0] ^= 1u;
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(rx_one(&r, msg, n, 64u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq));
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Rejections, each on a pristine copy of the last XRLE message. */
    uint8_t good[64];
    RWC_ASSERT(n <= sizeof good);
    memcpy(good, msg, n);
    SeSvpMsg bad = { SE_SVP_FRAME, good + SE_SVP_HDR_BYTES,
                     (uint32_t)(n - SE_SVP_HDR_BYTES) };
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W + 1u, H, fb, &seq)); /* geometry */
    good[SE_SVP_HDR_BYTES + 4u] = 9u;                        /* codec */
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W, H, fb, &seq));
    memcpy(good, msg, n);
    bad.len -= 4u;                                     /* truncated */
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W, H, fb, &seq));
    bad.len += 4u;
    good[SE_SVP_HDR_BYTES + 16u] = 0xFFu;              /* zeros past end */
    good[SE_SVP_HDR_BYTES + 19u] = 0x7Fu;
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W, H, fb, &seq));
    memcpy(good, msg, n);
    /* A (0,0) run followed by a run that would otherwise complete the
     * frame: only the no-progress guard rejects this (truncation does
     * not), so the guard is what this line tests. */
    uint8_t zz[SE_SVP_HDR_BYTES + 16u + 16u];
    memcpy(zz, msg, SE_SVP_HDR_BYTES + 16u);
    memset(zz + SE_SVP_HDR_BYTES + 16u, 0, 16u);
    zz[SE_SVP_HDR_BYTES + 24u] = (uint8_t)(W * H);
    zz[SE_SVP_HDR_BYTES + 25u] = (uint8_t)((W * H) >> 8);
    SeSvpMsg z = { SE_SVP_FRAME, zz + SE_SVP_HDR_BYTES, 32u };
    RWC_ASSERT(!SeSvp_apply_frame(&z, W, H, fb, &seq));
    zz[SE_SVP_HDR_BYTES + 16u] = 1u; /* control: (1,0),(W*H,0) overruns */
    RWC_ASSERT(!SeSvp_apply_frame(&z, W, H, fb, &seq));
    zz[SE_SVP_HDR_BYTES + 16u] = 0u;
    memmove(zz + SE_SVP_HDR_BYTES + 16u, zz + SE_SVP_HDR_BYTES + 24u, 8u);
    z.len = 24u; /* control: the lone (W*H,0) run is a valid frame */
    RWC_ASSERT(SeSvp_apply_frame(&z, W, H, fb, &seq));
    /* RAW with the wrong byte count. */
    z.len = 32u;
    zz[SE_SVP_HDR_BYTES + 4u] = SE_SVP_RAW;
    RWC_ASSERT(!SeSvp_apply_frame(&z, W, H, fb, &seq));
}

int main(void)
{
    test_sha256_vectors();
    test_hmac_vectors();
    test_ct_equal();
    test_auth_messages();
    test_token_rules();
    test_fixed_messages();
    test_rx_rejects();
    test_budgeted_stream();
    test_rate();
    test_frame_codec();
    printf("test_svp: ok\n");
    return 0;
}
