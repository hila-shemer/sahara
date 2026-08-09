import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_EMU = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_EMU)
for _p in (_ROOT, _EMU):
    if _p not in sys.path:
        sys.path.insert(0, _p)
