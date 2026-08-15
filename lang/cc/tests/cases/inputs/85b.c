// second unit of 85-multi-statics: its own 'secret' and 'peek'
static i64 secret = 222;
static i64 peek() { return secret; }
i64 other_peek() { return peek(); }
i64 other_bump() { secret = secret + 1; return 0; }
