// cc-error
// an incomplete forward tag cannot be sized or dereferenced-through
struct Later;
i64 main() {
    return (i64)sizeof(struct Later);
}
