# 01-ret42.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func main frame=0 calls=0
main:
        li r8, 42
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
