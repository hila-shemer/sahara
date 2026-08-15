// expect: 0x12d4ba
// oracle: no (struct Head holds a pointer: 16 bytes here, 8 on the host)
// struct self-reference through pointers and forward tags - the
// thinker-list shape; mutual recursion through the forward tag
struct Node;
struct Head { struct Node *first; i64 count; };
struct Node { i64 val; struct Node *next; struct Head *owner; };
struct Node nodes[4];
struct Head head;
i64 main() {
    i64 i;
    for (i = 0; i < 4; i++) {
        nodes[i].val = (i + 1) * 10;
        nodes[i].next = i < 3 ? &nodes[i + 1] : (struct Node *)0;
        nodes[i].owner = &head;
    }
    head.first = &nodes[0];
    head.count = 4;
    i64 t = 0;
    struct Node *p;
    for (p = head.first; p != 0; p = p->next) {
        t = t * 10 + p->val / 10;
    }
    t = t * 10 + (nodes[2].owner == &head ? 1 : 0);
    return t * 100 + head.count + (i64)sizeof(struct Head) / 16;
}
