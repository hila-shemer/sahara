// expect: 6200
i64 g2;
void setg(i64 v) { g2 = v; if (v > 100) return; g2 = g2 + 1; }
i64 main() { setg(5); i64 a = g2; setg(200); return a * 1000 + g2; }
