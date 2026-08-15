// expect: 0x84f
// switch over promoted sub-width and 32-bit controlling expressions;
// case constants beyond imm22 (materialized via li)
i64 main() {
    u8 tag = 200;
    i64 t = 0;
    switch (tag) {
    case 199: t = 1; break;
    case 200: t = 2; break;
    default: t = 3;
    }
    i32 code = -100000;
    switch (code) {
    case -100000: t = t * 10 + 1; break;
    case 100000: t = t * 10 + 2; break;
    default: t = t * 10 + 3;
    }
    i64 big = 123456789012345;
    switch (big) {
    case 123456789012344: t = t * 10 + 1; break;
    case 123456789012345: t = t * 10 + 2; break;   // needs li, no imm22
    default: t = t * 10 + 3;
    }
    u16 st = 65535;
    switch (st) {
    case 65535: t = t * 10 + 7; break;
    default: t = t * 10 + 9;
    }
    return t;
}
