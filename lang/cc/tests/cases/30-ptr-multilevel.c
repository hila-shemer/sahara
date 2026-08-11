// expect: 4521
i64 main() {
    i64 v = 42;
    i64 *p = &v;
    i64 **pp = &p;
    i64 ***ppp = &pp;
    **pp = **pp + 1;
    ***ppp = ***ppp + 2;
    i64 w = 7;
    *pp = &w;
    *p = *p * 3;
    return v * 100 + w;
}
