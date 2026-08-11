// expect: 12345
// oracle: no  (CC-M1 pins strict left-to-right; host C leaves it open)
i64 log_;
i64 rec(i64 v) { log_ = log_ * 10 + v; return v; }
i64 main() {
    log_ = 0;
    i64 x = rec(1) + rec(2) * rec(3);
    i64 arr3[4];
    arr3[rec(4) - 4] = rec(5);
    return log_;
}
