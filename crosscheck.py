#!/usr/bin/env python3
"""Verify encoding.py matches ISA-SPEC.md Appendix A. Run in CI forever."""
import re, sys
import encoding as E

spec = open(sys.argv[1]).read()
appendix = spec.split("## Appendix A")[1].split("## Appendix B")[0]
pairs = {}
for m in re.finditer(r'\|\s*0x([0-9A-F]{2})(?:/([0-9A-F]{2}))?\s*\|\s*([A-Z0-9]+)\s*\|', appendix):
    val, odd, name = int(m.group(1), 16), m.group(2), m.group(3)
    pairs[name] = (val, odd is not None)

errs = []
for name, (val, paired) in pairs.items():
    if name not in E.OPCODES:
        errs.append(f"spec has {name}, encoding.py lacks it")
        continue
    eval_, fam, _ = E.OPCODES[name]
    if eval_ != val:
        errs.append(f"{name}: spec 0x{val:02X} != encoding 0x{eval_:02X}")
    if E.FAMILIES[fam]["iflag"] != paired:
        errs.append(f"{name}: pairing mismatch (spec {'pair' if paired else 'single'})")
for name in E.OPCODES:
    if name not in pairs:
        errs.append(f"encoding.py has {name}, spec Appendix A lacks it")

# spot-check field table of section 3
for m in re.finditer(r'\|\s*(opcode|pred|dst|src1|src2|src3|mod|width|imm)\s*\|\s*(\d+)\s*\|\s*(\d+)[-–](\d+)\s*\|', spec):
    name, bits, lo, hi = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    elo, ebits = E.FIELDS[name]
    if (elo, ebits) != (lo, bits) or hi != lo + bits - 1:
        errs.append(f"field {name}: spec ({lo},{bits}) != encoding ({elo},{ebits})")

for e in errs: print("FAIL:", e)
print("OK: %d opcodes, %d fields cross-checked" % (len(pairs), len(E.FIELDS)) if not errs else f"{len(errs)} mismatches")
sys.exit(1 if errs else 0)
