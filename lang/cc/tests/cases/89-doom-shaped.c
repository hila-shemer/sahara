// expect: 0x00000000000000005632673144732624
// input: inputs/89-handlers.c
// maxcycles: 200000
// The DOOM-shaped exit exam (work-order decision 10): a const lookup
// table in rodata, an address-initialized dispatch table of
// { i32 tag; u16 next; i64 (*fn)(i32); } records in the second unit,
// and a switch-driven state machine over u16/i32 state, ticked a few
// thousand times into a running checksum.
typedef struct StateDef { i32 tag; u16 next; i64 (*fn)(i32); } StateDef;
extern StateDef states[];
extern const i32 wave[16];
extern i64 handler_calls();
static u64 chk = 0x5EED;
static void fold(i64 v) { chk = chk * 1000003 + (u64)v; }
i64 main() {
    u16 state = 0;
    i32 tick;
    for (tick = 0; tick < 1000; tick++) {
        StateDef *sd = &states[state];
        i64 r = sd->fn((i32)(tick & 15));
        switch (sd->tag) {
        case 0:
            fold(r + wave[tick & 15]);
            break;
        case 1:
        case 2:
            fold(r * 3 - sd->tag);
            break;
        case 5:
            fold(r ^ 0x55);
            /* fallthrough */
        case 7:
            fold((i64)state);
            break;
        default:
            fold(-1);
        }
        state = sd->next;
    }
    fold(handler_calls());
    return (i64)chk;
}
