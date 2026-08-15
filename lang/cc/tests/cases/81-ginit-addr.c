// expect: 5340093
// oracle: no
// address initializers - DOOM's states[] shape: function-pointer
// records, pointers into arrays, extern completion
extern i64 tab[];
i64 counter = 5;
i64 *pc = &counter;
i64 *pt2 = tab + 2;
i64 *pt3 = &tab[3];
i64 dbl(i32 x) { return x * 2; }
i64 neg3(i32 x) { return -3 * x; }
struct Op { i32 tag; i64 (*fn)(i32); };
struct Op ops[3] = {
    { 10, dbl },
    { 20, neg3 },
    { 30, (i64 (*)(i32))0 },
};
i64 tab[5] = { 11, 22, 33, 44, 55 };
i64 main() {
    i64 t = *pc;                                 // 5
    t = t * 100 + *pt2 + (pt3 - pt2);            // 33 + 1
    i64 i, acc = 0;
    for (i = 0; i < 3; i++) {
        acc = acc * 10 + ops[i].tag / 10;
        if (ops[i].fn != 0) { acc = acc + ops[i].fn((i32)i); }
    }
    // i=0: 1+dbl(0)=1; i=1: 12+neg3(1)=9... acc: 1 -> 1*10+2-3=9 -> 9*10+3=93
    return t * 10000 + acc;
}
