// expect: 230
// oracle: no
// fixture: asmlib.s
// C-calls-asm and asm-calls-C, plus an extern global defined in .s
extern i64 asm_add3(i64 a, i64 b, i64 c);
extern i64 asm_call_c(i64 x);
extern u64 asm_seed;
i64 c_scale(i64 x, i64 k) { return x * k; }
i64 main() {
    i64 t = asm_add3(100, 20, 3);
    t = t + asm_call_c(7);
    t = t + (i64)(asm_seed & 0xff);
    return t;
}
