/* Host-oracle wrapper: runs the case's main() (renamed cc_main via
 * -Dmain=cc_main) and prints the value exactly as the emulator's HALT
 * line would - the canonical 128-bit image (sign-extended from bit 63,
 * signed and unsigned alike, ISA 3.4) as 32 lowercase hex digits. */
#include <stdio.h>

extern long long cc_main(void);

int main(void) {
    unsigned __int128 c = (unsigned __int128)(__int128) cc_main();
    printf("%016llx%016llx\n",
           (unsigned long long)(c >> 64), (unsigned long long)c);
    return 0;
}
