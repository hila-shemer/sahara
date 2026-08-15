/* Host-oracle prelude - the include-guard trick (work-order decision
 * 6.5): LIBC_C is pre-defined here, so the case's #include "libc.c"
 * expands to NOTHING on the host and its mem and str calls resolve to
 * the HOST libc via <string.h> - a genuine two-implementation
 * differential on identical inputs. Cases clamp comparison results to
 * -1/0/1 themselves (our memcmp/strcmp return the byte difference,
 * the host's only its sign); cases whose truth is Sahara-only
 * (allocator addresses, conversion routines, capture output) say
 * "// oracle: no" instead.
 *
 * If this define ever drifts from libc.c's guard the differential
 * silently compares us to us; the break-our-memcmp check in the DoD
 * is the guard against that. */
#define LIBC_C 1

typedef unsigned char u8;
typedef long long i64;
typedef unsigned long long u64;
typedef __int128 i128;
typedef unsigned __int128 u128;

#include <string.h>
