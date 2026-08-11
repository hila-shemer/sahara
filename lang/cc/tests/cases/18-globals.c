// expect: 1270
// initialized data readback + partial array init zero-fill
i64 counter;
i64 arr[5] = { 3, 1, 4, 1 };
u64 big = 0xfeedfacefeedface;
u8 byte = 200;
i128 wide = 0 - 5;
i64 bump(i64 n) { counter = counter + n; return counter; }
i64 main() {
    bump(5);
    bump(7);
    i64 t = counter;
    t = t + arr[0]*1 + arr[2]*10 + arr[4]*100;
    t = t + (i64)(big >> 60);
    t = t + (i64)byte;
    if (wide == 0 - 5) t = t + 1000;
    return t;
}
