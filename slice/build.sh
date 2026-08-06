#!/bin/bash
# throwaway build script; ENC selects encoding config (A|B)
set -e
cd "$(dirname "$0")"
ENC=${ENC:-A}
python3 encoding.py "$ENC" encoding.h
gcc -O1 -g -Wall -Wextra -Wno-unused-parameter -o emu emu.c
