/* libc.c - the aggregator. A libc-using program is ONE translation
 * unit: it starts with #include "libc.c" and is built by
 * lib/c/ccbuild.sh (cpp -P -I lib/c, then cc.py, then asm.py). cpp is
 * used for #include and guards only - the language stays cc-m1.
 *
 * The guard below is also the host-oracle hook: the differential test
 * prelude pre-defines LIBC_C so this include becomes a no-op and the
 * case's mem and str calls resolve to the host's libc.
 */
#ifndef LIBC_C
#define LIBC_C

#include "libc.h"
#include "src/mem.c"
#include "src/str.c"
#include "src/alloc.c"
#include "src/conv.c"
#include "src/io.c"

#endif
