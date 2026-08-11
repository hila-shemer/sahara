// expect: 321616
// oracle: no  (pointers are 16 bytes on Sahara, 8 on the host)
struct P { u8 *s; i64 n; };
i64 main() {
    return (i64)(sizeof(u8*)*1 + sizeof(i64**)*100
         + sizeof(struct P)*10000);
}
