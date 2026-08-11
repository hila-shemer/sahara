// expect: 65228
i64 main() {
    i64 t = 'A' * 1000 + '\n' * 10 + '\x7f';
    if ('z' > 'a') t = t + 1;
    return t;
}
