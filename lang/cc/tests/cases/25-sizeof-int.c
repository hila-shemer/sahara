// expect: 2576818
struct T { i64 a; u8 b; i64 c; };
i64 main() {
    return (i64)(sizeof(i64)*1 + sizeof(u8)*10 + sizeof(u64)*100
         + sizeof(i128)*1000 + sizeof(u128)*10000
         + sizeof(struct T)*100000);
}
