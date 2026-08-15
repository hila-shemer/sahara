// expect: 0x51538
// input: inputs/85b.c
// same-named statics in different units do not collide - the
// correctness case cpp concatenation cannot express
static i64 secret = 111;
static i64 peek() { return secret; }
extern i64 other_peek();
extern i64 other_bump();
i64 main() {
    i64 t = peek() + other_peek();       // 111 + 222
    other_bump();
    t = t * 1000 + other_peek() - peek();  // 223 - 111
    return t;
}
