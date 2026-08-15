// expect: 0x69
// goto: forward, backward, into a scope (legal C89 and legal here -
// locals have frame slots for the whole function)
i64 main() {
    i64 t = 0;
    i64 i = 0;
    goto entry;                          // forward, into the loop scope
loop:
    t = t + i;
    i = i + 1;
entry:
    if (i < 5) { goto loop; }            // backward
    if (t == 10) { goto done; }
    t = 0;
done:
    return t * 10 + i;
}
