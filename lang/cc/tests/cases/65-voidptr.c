// expect: 0x6a63233
// void*: implicit T* <-> void* both ways, comparisons, cast round-trip
i64 g = 555;
void *keep(void *p) { return p; }
i64 main() {
    i64 x = 111;
    void *v = &x;                        // T* -> void* implicit
    i64 *p = v;                          // void* -> T* implicit
    i64 t = *p;
    v = keep(&g);
    t = t * 1000 + *(i64 *)v;            // explicit cast form too
    if (v == (void *)&g) { t = t * 10 + 1; }
    if (v != 0) { t = t * 10 + 2; }
    u8 *b = v;
    t = t * 10 + (v == b ? 3 : 4);       // void* vs u8* comparison
    return t;
}
