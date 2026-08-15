/* Host-oracle prelude (cc-m1.md test strategy, work-order 9.4): maps
 * CC-M1's type keywords onto host C so the same source compiles with
 * gcc. Pointer width differs (host 8 vs Sahara 16) - cases that depend
 * on it opt out with "// oracle: no". */
typedef unsigned char u8;
typedef signed char i8;
typedef unsigned short u16;
typedef short i16;
typedef unsigned int u32;
typedef int i32;
typedef long long i64;
typedef unsigned long long u64;
typedef __int128 i128;
typedef unsigned __int128 u128;
