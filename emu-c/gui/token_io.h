#ifndef SE_GUI_TOKEN_IO_H
#define SE_GUI_TOKEN_IO_H

#include <stdint.h>

#include "gui/svp.h"

/* The SVP shared token on disk (gui/svp.h, Authentication), loaded the
 * same way by sahara-serve and sahara-view. gui/token_io.c is a file
 * I/O carve-out like the socket shims; the rules it enforces --
 * permissions, owner, token shape -- are SeSvp_token_perm and
 * SeSvp_token_trim in gui/svp.c. */

/* ${XDG_CONFIG_HOME:-$HOME/.config}/sahara/serve-token into out
 * (cap bytes). Exits with a message when neither variable gives an
 * absolute directory or the path does not fit. */
void SeSvpToken_default_path(const char *prog, char *out, uint64_t cap);

/* Read the token at path into tok. Exits non-zero, naming the file
 * and the one command that fixes it, when the file is missing, not a
 * regular file, not owned by this user, readable by group or others,
 * or not SE_SVP_TOKEN_MIN..MAX bytes. */
void SeSvpToken_load(const char *prog, const char *path,
                     uint8_t tok[SE_SVP_TOKEN_MAX], uint32_t *tlen);

/* The token from a string (sahara-view's SAHARA_VIEW_TOKEN), trimmed
 * like a file's; exits non-zero when it is not a usable token. */
void SeSvpToken_from_env(const char *prog, const char *var, const char *val,
                         uint8_t tok[SE_SVP_TOKEN_MAX], uint32_t *tlen);

#endif /* SE_GUI_TOKEN_IO_H */
