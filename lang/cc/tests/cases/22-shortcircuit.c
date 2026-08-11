// expect: 163
// && / || short-circuit: RHS side effects must not happen
i64 calls;
i64 bump(i64 v) { calls = calls + 1; return v; }
i64 main() {
    i64 t = 0;
    calls = 0;
    if (0 && bump(1)) t = t + 1000;
    if (t == 0) t = t + 1;
    if (1 || bump(1)) t = t + 2;
    if (calls == 0) t = t + 4;
    if (1 && bump(1)) t = t + 8;
    if (0 || bump(2)) t = t + 16;
    if (calls == 2) t = t + 32;
    i64 v = (5 && 3);
    i64 w = (0 || 0);
    return t + v * 100 + w;
}
