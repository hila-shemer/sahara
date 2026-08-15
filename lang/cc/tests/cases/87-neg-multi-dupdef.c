// cc-error
// input: inputs/87b.c
// one non-static definition per symbol across the whole set
i64 shared = 5;
i64 main() { return shared; }
