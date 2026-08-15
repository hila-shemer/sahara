// cc-error
// case values convert to the promoted controlling type first:
// 0x100000000 converts to i32 0 - a duplicate of case 0
i64 main() {
    i32 x = 0;
    switch (x) {
    case 0: return 1;
    case 0x100000000: return 2;
    }
    return 0;
}
