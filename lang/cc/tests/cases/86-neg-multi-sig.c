// cc-error
// input: inputs/86b.c
// conflicting cross-unit signatures: the diagnostic names both files
extern i64 helper(i64 x);
i64 main() { return helper(1); }
