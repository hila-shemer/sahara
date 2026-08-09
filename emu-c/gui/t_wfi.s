# t_wfi.s — seam-driver guest for the WFI-idle scenario (run-gui-tests):
# handler-driven, idles in WFI between deliveries. The driver feeds a
# key press while the core is yielded (live_yield), which must produce
# the EXEC(WFI)@C, EVENT@E, TRAP@E shape and replay byte-identically
# through the headless jump (SPEC-ISSUES 36). Press keeps waiting,
# release halts with the pass magic.

        .equ DEV_KBD_BASE, 0x0F010000
        .equ PASS_MAGIC, 0x600D

        .org 0x1000
start:
        la.abs r19, h_ext
        mtsr vbase, r19
        li r19, 9              # STATUS_S | STATUS_IE
        mtsr status, r19
loop:
        wfi                    # idles: no timer, feed not arrived yet
        b loop

        # EXTINT handler: drain the keyboard; a release event ends the
        # session, presses just go back to waiting.
h_ext:
        li r17, DEV_KBD_BASE
hd:
        lds.64 k0, [r17]       # DATA pop (sentinel sign-extends to -1)
        cmpeq p3, k0, -1
        (p3) b hd_done
        li r16, 1
        shl r16, r16, 32       # bit 32 = press
        and r16, k0, r16
        cmpeq p2, r16, 0
        (p2) b halt_now        # release -> done
        b hd
hd_done:
        iret
halt_now:
        li r0, PASS_MAGIC
        halt
