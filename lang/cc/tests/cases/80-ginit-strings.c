// expect: 0x1a126d71aa
// string initializers: sized u8 arrays (NUL + zero fill), exact fit,
// size inference, and u8* into the shared rodata pool
u8 hello[8] = "hello";
u8 exact[2] = "ab";
u8 inferred[] = "world";
u8 *pmsg = "pooled";
const u8 *cmsg = "pooled";
i64 main() {
    i64 t = (i64)hello[4] + (i64)hello[6];       // 'o' + 0
    t = t * 100 + (i64)exact[1];                 // 'b'
    t = t * 100 + (i64)(inferred[4] - inferred[0]);  // 'd'-'w' = -19
    t = t * 100 + (i64)pmsg[0] + (i64)cmsg[5];   // 'p' + 'd'
    t = t * 10 + (pmsg == cmsg ? 1 : 0);         // pooled: same object
    t = t * 100 + (i64)sizeof(inferred);         // 6
    return t;
}
