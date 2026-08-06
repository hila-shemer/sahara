#!/usr/bin/env python3
# histogram of signed bit-widths needed by logged immediates, per kind and total
import sys, collections
def bits_needed(v):
    # smallest n such that v fits signed n-bit
    n = 1
    while not (-(1 << (n-1)) <= v < (1 << (n-1))): n += 1
    return n
per_kind = collections.defaultdict(list)
for line in open(sys.argv[1]):
    kind, v = line.split()
    per_kind[kind].append(bits_needed(int(v)))
allbits = []
for kind, bl in sorted(per_kind.items()):
    bl.sort()
    allbits += bl
    pct = lambda p: bl[min(len(bl)-1, int(len(bl)*p))]
    print(f"{kind:10s} n={len(bl):5d} max={bl[-1]:3d} p50={pct(.5):3d} p90={pct(.9):3d} p99={pct(.99):3d}")
allbits.sort()
n = len(allbits)
print(f"{'ALL':10s} n={n:5d} max={allbits[-1]:3d}")
for w in (12, 16, 20, 24, 28, 32):
    fit = sum(1 for b in allbits if b <= w)
    print(f"  fits in {w:2d} bits: {100.0*fit/n:6.2f}%")
