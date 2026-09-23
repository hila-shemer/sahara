/* The SVP token on disk (gui/token_io.h). File I/O carve-out on
 * nic_host.c's pattern: allow_banned, out of the source audits, linked
 * only into sahara-serve and sahara-view. It reads one small file and
 * reports; the rules are gui/svp.c's. */
#include "gui/token_io.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

RWC_NORETURN static void fail(const char *prog, const char *msg,
                              const char *path, const char *fix)
{
    fprintf(stderr, "%s: %s: %s\n", prog, msg, path);
    if (fix)
        fprintf(stderr, "%s: fix: %s\n", prog, fix);
    exit(1);
}

void SeSvpToken_default_path(const char *prog, char *out, uint64_t cap)
{
    const char *xdg = getenv("XDG_CONFIG_HOME");
    const char *home = getenv("HOME");
    int n;
    /* XDG base-directory rule: a relative XDG_CONFIG_HOME is invalid
     * and ignored. */
    if (xdg && xdg[0] == '/')
        n = snprintf(out, (size_t)cap, "%s/sahara/serve-token", xdg);
    else if (home && home[0] == '/')
        n = snprintf(out, (size_t)cap, "%s/.config/sahara/serve-token", home);
    else {
        fprintf(stderr, "%s: no HOME or XDG_CONFIG_HOME to find the "
                        "token file in; pass --token-file PATH\n", prog);
        exit(1);
    }
    if (n < 0 || (uint64_t)n >= cap) {
        fprintf(stderr, "%s: token file path too long\n", prog);
        exit(1);
    }
}

/* The one-line command that creates a good token file at path. */
static void create_cmd(const char *path, char *out, size_t cap)
{
    const char *slash = strrchr(path, '/');
    if (slash && slash != path)
        (void)snprintf(out, cap,
                       "umask 077; mkdir -p '%.*s' && head -c 32 "
                       "/dev/urandom | base64 > '%s'",
                       (int)(slash - path), path, path);
    else
        (void)snprintf(out, cap,
                       "umask 077; head -c 32 /dev/urandom | base64 > '%s'",
                       path);
}

void SeSvpToken_load(const char *prog, const char *path,
                     uint8_t tok[SE_SVP_TOKEN_MAX], uint32_t *tlen)
{
    char fix[2 * 4096 + 128];
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOCTTY);
    if (fd < 0) {
        if (errno == ENOENT) {
            create_cmd(path, fix, sizeof fix);
            fail(prog, "no token file", path, fix);
        }
        fail(prog, strerror(errno), path, NULL);
    }
    struct stat st;
    if (fstat(fd, &st) != 0)
        fail(prog, "cannot stat token file", path, NULL);
    switch (SeSvp_token_perm(S_ISREG(st.st_mode), (uint32_t)st.st_mode,
                             (uint32_t)st.st_uid, (uint32_t)geteuid())) {
    case SE_SVP_TOKEN_PERM_OK:
        break;
    case SE_SVP_TOKEN_NOT_REGULAR:
        fail(prog, "token file is not a regular file", path, NULL);
    case SE_SVP_TOKEN_WRONG_OWNER:
        fail(prog, "token file is owned by another user", path,
             "create your own (see frontend-notes.md, Remote)");
    case SE_SVP_TOKEN_TOO_OPEN: {
        char msg[64];
        (void)snprintf(msg, sizeof msg,
                       "token file is mode %04o, must be 0600 or stricter",
                       (unsigned)(st.st_mode & 07777u));
        (void)snprintf(fix, sizeof fix, "chmod 600 '%s'", path);
        fail(prog, msg, path, fix);
    }
    }
    /* One byte past the cap tells "too long" from "exactly the cap"
     * after trimming; a little more leaves room for the newline. */
    uint8_t buf[SE_SVP_TOKEN_MAX + 64];
    uint64_t len = 0;
    for (;;) {
        ssize_t n = read(fd, buf + len, sizeof buf - len);
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0)
            fail(prog, "cannot read token file", path, NULL);
        if (n == 0 || (len += (uint64_t)n) == sizeof buf)
            break;
    }
    close(fd);
    if (!SeSvp_token_trim(buf, len, tlen)) {
        create_cmd(path, fix, sizeof fix);
        fail(prog, "token file must hold 16..1024 bytes of text", path, fix);
    }
    memcpy(tok, buf, *tlen);
    memset(buf, 0, sizeof buf);
}

void SeSvpToken_from_env(const char *prog, const char *var, const char *val,
                         uint8_t tok[SE_SVP_TOKEN_MAX], uint32_t *tlen)
{
    uint64_t len = strlen(val);
    if (!SeSvp_token_trim((const uint8_t *)val, len, tlen)) {
        fprintf(stderr, "%s: %s must hold 16..1024 bytes\n", prog, var);
        exit(1);
    }
    memcpy(tok, val, *tlen);
}
