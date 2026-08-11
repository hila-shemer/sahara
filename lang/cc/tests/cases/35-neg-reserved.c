// cc-error
// a legal C program whose name collides with an assembler mnemonic
i64 add(i64 a, i64 b) { return a + b; }
i64 main() { return add(1, 2); }
