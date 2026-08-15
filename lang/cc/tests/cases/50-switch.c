// expect: 0xbb4ba7
// switch essentials: source-order chain, fallthrough, break, default,
// nested switch. This is the switch-chain golden.
i64 classify(i64 x) {
    i64 r = 0;
    switch (x) {
    case 0:
        r = 100;
        break;
    case 1:
    case 2:
        r = 200;                 // 1 and 2 share a body
        break;
    case 3:
        r = 300;                 // falls through into 4
    case 4:
        r = r + 400;
        break;
    case 5:
        switch (x * 2) {         // nested switch owns its own cases
        case 10:
            r = 510;
            break;
        default:
            r = 599;
        }
        break;
    default:
        r = 999;
    }
    return r;
}
i64 main() {
    i64 t = 0;
    i64 i = 0;
    while (i < 8) {
        t = t * 10 + classify(i) / 100;
        i = i + 1;
    }
    return t;
}
