# netboot.s - the Sahara netboot ROM: a resident tiny OS whose whole
# job is "the network is the storage layer". It validates the device
# table, finds NIC + timer (+ display, optional) BY TYPE, fetches "the
# image" over SBP/1 from 10.0.2.2:69 (rom/netboot/sbp.md), parses
# SAHIMG01 in-guest, and copy-downs the payload over itself. Every
# terminal failure paints a message on the framebuffer (when a display
# exists) and HALTs with a distinct r0 code - loud, never a hang.
#
# Structure (kept separable on purpose - a future resident payload,
# e.g. a fallback monitor when no server answers, reuses the console
# and fetch modules as-is):
#   boot     - table validation + device scan (boot.md 6; the scan is
#              a reduction of os/oasis/kernel/boot.s boot_dev_loop)
#   fetch    - SBP/1 client: stop-and-wait, timer-COUNT retransmit
#   image    - SAHIMG01 validation + relocated two-stage copy-down
#   console  - error paint + 8x16 text rendering (font.s)
#
# Error codes (frozen; sbp.md section 6 is the normative copy):
#   0xBAD1  device-table validation failed (incl. u128 high halves)
#   0xBAD2  no NIC (type 4) in the table
#   0xBAD3  no timer (type 5) in the table
#   0xBAD4  fetch timeout: RETRY_MAX sends, no reply
#   0xBAD5  server ERR (any code; 1 = no image configured)
#   0xBAD6  image bad magic / entry / nsegs
#   0xBAD7  segment truncated or out of bounds
#   0xBAD8  staging overflow / image too big / RAM too small to stage
#
# Register map (ROM-lifetime; boot owns the machine, no ABI until the
# hand-off zeroes everything):
#   r20 NIC regs   r21 TX buf      r22 RX buf     r23 timer regs
#   r24 display regs (0 = none)    r25 pixel buffer PA
#   r26 region-0 top               r27 stage_base r19 stage_limit
#   r18 download cursor            r17 expected block
#   r16 COUNT at last send         r15 retries left
#   r14 current TX template        r13 MAC (table params[0])
#   r12 TIMEOUT_CYCLES             r1-r9 scratch
#   fail path only: r7 color, r8 message, r10/r11 console cursor

        .equ DT_BASE, 0x800            # the one hardcodable address
        .equ DT_MAGIC, 0x5450415241484153
        .equ DT_VERSION, 1
        .equ DT_WINDOW, 2048
        .equ IMG_MAGIC, 0x3130474D49484153  # "SAHIMG01"

        # Liveness backstop only: on the lossless local plane a reply
        # either arrives or never will (--nic off / no translator), so
        # the retransmit path is unreachable in practice - do not
        # "fix" the dup-DATA handling into complexity. 5 x 8M cycles
        # = ~20 s at the default 2 MHz before 0xBAD4.
        .equ TIMEOUT_CYCLES, 8000000
        .equ RETRY_MAX, 5

        .equ SBP_BLOCK, 1024
        # Staging never starts below 64 KB: keeps it structurally
        # clear of the ROM itself (build.sh asserts the image ends
        # below this) without a link-time end symbol.
        .equ STAGE_FLOOR, 0x10000

        .equ HALT_DEVTAB, 0xBAD1
        .equ HALT_NONIC, 0xBAD2
        .equ HALT_NOTIMER, 0xBAD3
        .equ HALT_TIMEOUT, 0xBAD4
        .equ HALT_SRVERR, 0xBAD5
        .equ HALT_BADIMG, 0xBAD6
        .equ HALT_BADSEG, 0xBAD7
        .equ HALT_TOOBIG, 0xBAD8

        # Error-screen background colors (XRGB8888), dark so the white
        # text reads; one per class, also useful to a human at a
        # glance when the message is off-screen in a tiny mode.
        .equ CLR_DEVTAB, 0x00800000
        .equ CLR_NONIC, 0x00804000
        .equ CLR_NOTIMER, 0x00806000
        .equ CLR_TIMEOUT, 0x00000080
        .equ CLR_SRVERR, 0x00600060
        .equ CLR_BADIMG, 0x00006060
        .equ CLR_BADSEG, 0x00006000
        .equ CLR_TOOBIG, 0x00404040

        .org 0x1000
        .entry _reset
_reset:
        b       _start
        .ascii "SBROM v1"              # greppable in image and RAM

# --------------------------------------------------------------- boot

_start:
        li      r1, DT_BASE
        ldz.64  r2, [r1 + 0]
        li      r3, DT_MAGIC
        cmpeq   p1, r2, r3
        (!p1) b fail_devtab
        ldz.64  r2, [r1 + 8]
        cmpeq   p1, r2, DT_VERSION
        (!p1) b fail_devtab
        ldz.64  r4, [r1 + 24]          # ram_region_count
        ldz.64  r5, [r1 + 32]          # device_count
        cmpltu  p1, zero, r4           # >= 1 region
        (!p1) b fail_devtab
        mul     r6, r4, 32
        mul     r7, r5, 64
        add     r6, r6, r7
        add     r6, r6, 40
        cmpleu  p1, r6, DT_WINDOW      # encoded size fits the window
        (!p1) b fail_devtab

        # Region 0 sizes everything (multi-region RAM stages in region
        # 0, like the Oasis kernel). u128 fields are 8-aligned only:
        # paired ldz.64, loud on a nonzero high half (boot.md 3.2).
        ldz.64  r2, [r1 + 40]          # base lo
        ldz.64  r3, [r1 + 48]          # base hi
        ldz.64  r6, [r1 + 56]          # len lo
        ldz.64  r7, [r1 + 64]          # len hi
        or      r3, r3, r7
        cmpeq   p1, r3, zero
        (!p1) b fail_devtab
        add     r26, r2, r6            # top = base + len

        # Staging policy, derived, never hardcoded (work order 4.4):
        #   stage_cap  = (len/2) & ~0xFFFF   - half of region 0
        #   stage_base = (top - 64K - cap) & ~0xFFFF
        # Top 64 KB is the SABI 4.5 boot-stack window; the relocated
        # copy loop lands at its base, always RAM, never a payload
        # target. Payload territory is [0x1000, stage_base) - at
        # least half of RAM by construction. shr/shl does the 64 KB
        # alignment without a mask register.
        shr     r2, r6, 17
        shl     r2, r2, 16             # stage_cap
        li      r3, 0x10000
        sub     r27, r26, r3
        sub     r27, r27, r2
        shr     r27, r27, 16
        shl     r27, r27, 16           # stage_base
        add     r19, r27, r2           # stage_limit

        # Device walk, by count, first-record-of-type wins, unknown
        # types skip by the unconditional +64 (the boot_dev_loop idiom
        # from os/oasis/kernel/boot.s; boot.md 4.2). Positions are
        # never assumed - the table order changed once already when
        # rng/timer/dma landed.
        mul     r6, r4, 32
        add     r6, r6, 40
        add     r6, r6, r1             # r6 -> first device record
dev_loop:
        cmpeq   p1, r5, zero
        (p1) b  dev_done
        ldz.64  r7, [r6 + 0]           # type
        cmpeq   p2, r7, 4
        (p2) b  dev_nic
        cmpeq   p2, r7, 5
        (p2) b  dev_timer
        cmpeq   p2, r7, 1
        (p2) b  dev_disp
        b       dev_next
dev_nic:
        cmpeq   p3, r20, zero
        (!p3) b dev_next               # not the first of its type
        ldz.64  r2, [r6 + 8]           # base lo
        ldz.64  r3, [r6 + 16]          # base hi
        cmpeq   p3, r3, zero
        (!p3) b fail_devtab
        mov     r20, r2
        ldz.64  r13, [r6 + 32]         # params[0]: MAC, boot.md 3.6
        b       dev_next
dev_timer:
        cmpeq   p3, r23, zero
        (!p3) b dev_next
        ldz.64  r2, [r6 + 8]
        ldz.64  r3, [r6 + 16]
        cmpeq   p3, r3, zero
        (!p3) b fail_devtab
        mov     r23, r2
        b       dev_next
dev_disp:
        cmpeq   p3, r24, zero
        (!p3) b dev_next
        ldz.64  r2, [r6 + 8]
        ldz.64  r3, [r6 + 16]
        cmpeq   p3, r3, zero
        (!p3) b fail_devtab
        mov     r24, r2
        ldz.64  r25, [r6 + 32]         # params[0]: pixel buffer PA
        b       dev_next
dev_next:
        add     r6, r6, 64
        sub     r5, r5, 1
        b       dev_loop
dev_done:
        cmpeq   p1, r20, zero
        (p1) b  fail_nonic
        cmpeq   p1, r23, zero
        (p1) b  fail_notimer
        li      r2, 0x10000
        add     r21, r20, r2           # TX buffer (window +0x10000)
        add     r22, r21, r2           # RX buffer (window +0x20000)
        mov     sp, r26                # SABI 4.5 boot stack (unused)

        li      r2, STAGE_FLOOR
        cmpleu  p1, r2, r27
        (!p1) b fail_toobig            # RAM too small to stage at all

        # Patch the guest MAC (a table value, never a constant - the
        # source MAC is unchecked by classification, but lying in a
        # recorded trace helps nobody) into both TX templates.
        la      r1, req_frame
        jal     mac_patch
        la      r1, ack_frame
        jal     mac_patch

# -------------------------------------------------------------- fetch
# SBP/1 client (sbp.md section 4): REQ elicits DATA(1); ACK(n) elicits
# DATA(n+1); a DATA payload short of 1024 is final. No DHCP, no ARP:
# classification accepts src 10.0.2.15 unconditionally and the peer
# MAC is normative (nic.md 6.1), so both TX frames are fixed 60-byte
# templates with an assemble-time IP checksum.

        li      r12, TIMEOUT_CYCLES
        la      r14, req_frame
        li      r17, 1                 # expecting DATA(1)
        mov     r18, r27               # cursor = stage_base
        li      r15, RETRY_MAX
        jal     send_cur
poll_loop:
        ldz.64  r2, [r20 + 16]         # RX_LEN
        cmpltu  p1, zero, r2
        (p1) b  got_frame
        ldz.64  r3, [r23 + 0]          # timer COUNT (timer.md 2)
        sub     r3, r3, r16
        cmpltu  p1, r3, r12
        (p1) b  poll_loop
        sub     r15, r15, 1            # timeout: retry or give up
        cmpeq   p1, r15, zero
        (p1) b  fail_timeout
        jal     send_cur               # resend the last REQ/ACK
        b       poll_loop

got_frame:
        # Only SBP replies can arrive (the ROM never opens a flow and
        # the plane has no unsolicited inbound, nic.md 6.9.1); the
        # checks below are cheap armor, and anything else pops and
        # keeps polling. Ports/IPs read as little-endian halfwords of
        # the big-endian wire bytes - the .equ-style constants inline.
        ldz.16  r2, [r22 + 12]
        cmpeq   p1, r2, 0x0008         # EtherType 0x0800
        (!p1) b drop_frame
        ldz.8   r2, [r22 + 23]
        cmpeq   p1, r2, 17             # UDP
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 26]
        cmpeq   p1, r2, 0x000A         # src IP 10.0.2.2 ...
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 28]
        cmpeq   p1, r2, 0x0202
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 34]
        cmpeq   p1, r2, 0x4500         # src port 69
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 36]
        cmpeq   p1, r2, 0x07B0         # dst port 45063 (0xB007)
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 42]
        cmpeq   p1, r2, 0x4253         # "SB"
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 44]
        cmpeq   p1, r2, 0x3150         # "P1"
        (!p1) b drop_frame
        ldz.8   r2, [r22 + 38]         # UDP length, big-endian
        shl     r2, r2, 8
        ldz.8   r3, [r22 + 39]
        or      r2, r2, r3
        cmpltu  p1, r2, 20             # >= 8 UDP + 12 SBP header
        (p1) b  drop_frame
        sub     r5, r2, 20             # r5 = DATA payload length
        ldz.16  r2, [r22 + 46]         # opcode (LE u32 at +46)
        ldz.16  r3, [r22 + 48]
        cmpeq   p1, r3, zero
        (!p1) b drop_frame
        cmpeq   p1, r2, 4              # ERR: terminal immediately,
        (p1) b  fail_srverr            # no retries (sbp.md 6)
        cmpeq   p1, r2, 2
        (!p1) b drop_frame
        ldz.16  r2, [r22 + 50]         # block (LE u32 at +50)
        ldz.16  r3, [r22 + 52]
        shl     r3, r3, 16
        or      r2, r2, r3
        cmpeq   p1, r2, r17            # only the expected block; a
        (!p1) b drop_frame             # dup re-elicits, timer covers
        cmpleu  p1, r5, SBP_BLOCK
        (!p1) b drop_frame             # server never sends more
        add     r2, r18, r5
        cmpleu  p1, r2, r19            # staging overflow, checked
        (!p1) b fail_toobig            # before the copy
        add     r1, r22, 54            # copy the payload down
        mov     r2, r18
        mov     r3, r5
cp1:
        cmpeq   p1, r3, zero
        (p1) b  cp_done
        ldz.8   r4, [r1]
        st.8    [r2], r4
        add     r1, r1, 1
        add     r2, r2, 1
        sub     r3, r3, 1
        b       cp1
cp_done:
        add     r18, r18, r5
        st.64   [r20 + 24], zero       # RX_POP: frame consumed
        cmpltu  p1, r5, SBP_BLOCK
        (p1) b  parse_image            # short block = final
        la      r1, ack_frame          # full block: ACK it
        st.16   [r1 + 50], r17
        shr     r2, r17, 16
        st.16   [r1 + 52], r2
        mov     r14, r1
        add     r17, r17, 1
        li      r15, RETRY_MAX
        jal     send_cur
        b       poll_loop

drop_frame:
        st.64   [r20 + 24], zero       # RX_POP
        b       poll_loop

        # send_cur: copy the 60-byte template at r14 into the TX
        # buffer, ring the doorbell, restamp the timeout epoch.
        # Clobbers r1-r4.
send_cur:
        mov     r1, r14
        mov     r2, r21
        li      r3, 60
sc1:
        ldz.8   r4, [r1]
        st.8    [r2], r4
        add     r1, r1, 1
        add     r2, r2, 1
        sub     r3, r3, 1
        cmpltu  p1, zero, r3
        (p1) b  sc1
        li      r3, 60
        st.64   [r20 + 0], r3          # TX_DOORBELL
        ldz.64  r16, [r23 + 0]         # epoch = COUNT after the send
        ret

        # mac_patch: write r13's low 6 bytes (boot.md 3.6 packing:
        # wire order = byte order) at [r1+6..11]. Clobbers r1-r3.
mac_patch:
        mov     r2, r13
        li      r3, 6
        add     r1, r1, 6
mp1:
        st.8    [r1], r2
        shr     r2, r2, 8
        add     r1, r1, 1
        sub     r3, r3, 1
        cmpltu  p1, zero, r3
        (p1) b  mp1
        ret

# -------------------------------------------------------------- image
# SAHIMG01 in-guest (TOOLING-SPEC 1, first in-guest consumer). Checks:
# magic; entry u128 (high half 0, 8-aligned, in payload territory);
# nsegs in [1,64]; per segment file window inside the download,
# mem_len >= file_len, no u64 wraps, target inside [0x1000,
# stage_base) - which structurally protects the [0,0x800) tripwire,
# the device table, the staging window and the stack in one check.
# Segment-vs-segment overlap is NOT checked: the ROM is not a linker,
# the host assembler already refuses overlap, and a hand-hostile
# image gets last-writer-wins (copy order = table order).

parse_image:
        sub     r1, r18, r27           # downloaded length
        cmpltu  p1, r1, 32             # 8 magic + 16 entry + 8 nsegs
        (p1) b  fail_badimg            # shorter than the header
        ldz.64  r2, [r27 + 0]
        li      r3, IMG_MAGIC
        cmpeq   p1, r2, r3
        (!p1) b fail_badimg
        ldz.64  r6, [r27 + 8]          # entry lo
        ldz.64  r3, [r27 + 16]         # entry hi
        cmpeq   p1, r3, zero
        (!p1) b fail_badimg
        and     r3, r6, 7
        cmpeq   p1, r3, zero
        (!p1) b fail_badimg            # entry must be 8-aligned
        li      r3, 0x1000
        cmpleu  p1, r3, r6
        (!p1) b fail_badimg
        cmpltu  p1, r6, r27
        (!p1) b fail_badimg            # entry outside payload land
        ldz.64  r7, [r27 + 24]         # nsegs
        cmpltu  p1, zero, r7
        (!p1) b fail_badimg
        cmpleu  p1, r7, 64
        (!p1) b fail_badimg
        mul     r2, r7, 48
        add     r2, r2, 32
        cmpleu  p1, r2, r1             # descriptor table downloaded
        (!p1) b fail_badseg

        # The relocated copy loop goes to top - 64K (the stack window
        # base - always RAM, never a payload target); the parsed
        # segment table right after it, 16-aligned.
        li      r2, 0x10000
        sub     r8, r26, r2            # r8 = reloc_base
        la      r3, copydown_start
        la      r4, copydown_end
        sub     r4, r4, r3
        add     r9, r8, r4
        add     r9, r9, 15
        and     r9, r9, -16            # r9 = relocated seg table

        add     r10, r27, 32           # r10 -> first descriptor
        mov     r11, r9                # r11 -> table row out
        mov     r5, r7
seg_loop:
        cmpeq   p1, r5, zero
        (p1) b  seg_done
        ldz.64  r2, [r10 + 16]         # file_off
        ldz.64  r3, [r10 + 24]         # file_len
        ldz.64  r4, [r10 + 32]         # mem_len
        add     r1, r2, r3
        cmpleu  p1, r2, r1             # u64 wrap in off+len
        (!p1) b fail_badseg
        sub     r0, r18, r27
        cmpleu  p1, r1, r0             # file window inside download
        (!p1) b fail_badseg
        cmpleu  p1, r3, r4             # mem_len >= file_len
        (!p1) b fail_badseg
        ldz.64  r0, [r10 + 0]          # load_pa lo
        ldz.64  r1, [r10 + 8]          # load_pa hi
        cmpeq   p1, r1, zero
        (!p1) b fail_badseg
        li      r1, 0x1000
        cmpleu  p1, r1, r0
        (!p1) b fail_badseg            # below the reset PC
        add     r1, r0, r4
        cmpleu  p1, r0, r1             # u64 wrap in pa+mem_len
        (!p1) b fail_badseg
        cmpleu  p1, r1, r27
        (!p1) b fail_badseg            # into staging/stack territory
        st.64   [r11 + 0], r0          # row: dst
        add     r1, r27, r2
        st.64   [r11 + 8], r1          # row: src (staged bytes)
        st.64   [r11 + 16], r3         # row: file_len
        st.64   [r11 + 24], r4         # row: mem_len
        add     r11, r11, 32
        add     r10, r10, 48
        sub     r5, r5, 1
        b       seg_loop
seg_done:
        la      r1, copydown_start     # copy the loop to reloc_base
        la      r2, copydown_end
        mov     r3, r8
cc1:
        cmpltu  p1, r1, r2
        (!p1) b cc_done
        ldz.64  r4, [r1]
        st.64   [r3], r4
        add     r1, r1, 8
        add     r3, r3, 8
        b       cc1
cc_done:
        ifence                         # about to execute what we wrote
        mov     r1, r9                 # relocated seg table
        mov     r2, r7                 # nsegs
        mov     r3, r6                 # entry
        jalr    zero, r8, 0            # no return

# The two-stage copy-down. This block executes RELOCATED at top-64K,
# so it must be genuinely position-independent: register arithmetic
# and local branches only - no la/lap (their PC-relative offsets
# would resolve against the assembled address, not the relocated
# one). It is the only ROM code that survives the overwrite; the CI
# payload's segments cover the ROM's whole footprint to prove it.
# In: r1 = seg table rows (dst, src, file_len, mem_len), r2 = count,
# r3 = entry. Ends in a reset-like hand-off: r0-r30 and p1-p7 zeroed,
# jump to entry via epc0 + IRET (a jalr would leave the entry address
# visible in a register; IRET reads pc from a sreg, so every GPR can
# be zero). Deltas from a cold reset, documented in sbp.md: cycle,
# NIC pop-state and timer are NOT reset, epc0 = entry, status.PS = 1.
copydown_start:
cd_seg:
        cmpeq   p1, r2, zero
        (p1) b  cd_done
        ldz.64  r4, [r1 + 0]           # dst
        ldz.64  r5, [r1 + 8]           # src
        ldz.64  r6, [r1 + 16]          # file_len
        ldz.64  r7, [r1 + 24]          # mem_len
        sub     r8, r7, r6             # zero-fill tail length
cd_copy:
        cmpeq   p1, r6, zero
        (p1) b  cd_zero
        ldz.8   r9, [r5]
        st.8    [r4], r9
        add     r4, r4, 1
        add     r5, r5, 1
        sub     r6, r6, 1
        b       cd_copy
cd_zero:
        cmpeq   p1, r8, zero
        (p1) b  cd_next
        st.8    [r4], zero
        add     r4, r4, 1
        sub     r8, r8, 1
        b       cd_zero
cd_next:
        add     r1, r1, 32
        sub     r2, r2, 1
        b       cd_seg
cd_done:
        ifence                         # payload code just written
        mtsr    epc0, r3
        li      r4, 0x18               # S|PS: IRET stays supervisor,
        mtsr    status, r4             # IE stays 0 (PIE = 0)
        pwr     zero                   # p1-p7 <- 0 (p0 hardwired 1)
        mov     r0, zero
        mov     r1, zero
        mov     r2, zero
        mov     r3, zero
        mov     r4, zero
        mov     r5, zero
        mov     r6, zero
        mov     r7, zero
        mov     r8, zero
        mov     r9, zero
        mov     r10, zero
        mov     r11, zero
        mov     r12, zero
        mov     r13, zero
        mov     r14, zero
        mov     r15, zero
        mov     r16, zero
        mov     r17, zero
        mov     r18, zero
        mov     r19, zero
        mov     r20, zero
        mov     r21, zero
        mov     r22, zero
        mov     r23, zero
        mov     r24, zero
        mov     r25, zero
        mov     r26, zero
        mov     r27, zero
        mov     r28, zero
        mov     r29, zero
        mov     r30, zero
        iret                           # pc <- epc0 = entry
copydown_end:

# ------------------------------------------------------------ console
# Failure discipline: paint + message + PRESENT + HALT (never a
# silent hang). r0 carries the halt code through the console code
# untouched - it is what headless CI asserts; the text is for the
# human at the window. No display found (r24 = 0): straight to HALT.

fail_devtab:
        li      r0, HALT_DEVTAB
        li      r7, CLR_DEVTAB
        la      r8, msg_devtab
        b       fail_common
fail_nonic:
        li      r0, HALT_NONIC
        li      r7, CLR_NONIC
        la      r8, msg_nonic
        b       fail_common
fail_notimer:
        li      r0, HALT_NOTIMER
        li      r7, CLR_NOTIMER
        la      r8, msg_notimer
        b       fail_common
fail_timeout:
        li      r0, HALT_TIMEOUT
        li      r7, CLR_TIMEOUT
        la      r8, msg_timeout
        b       fail_common
fail_srverr:
        li      r0, HALT_SRVERR
        li      r7, CLR_SRVERR
        la      r8, msg_srverr
        b       fail_common
fail_badimg:
        li      r0, HALT_BADIMG
        li      r7, CLR_BADIMG
        la      r8, msg_badimg
        b       fail_common
fail_badseg:
        li      r0, HALT_BADSEG
        li      r7, CLR_BADSEG
        la      r8, msg_badseg
        b       fail_common
fail_toobig:
        li      r0, HALT_TOOBIG
        li      r7, CLR_TOOBIG
        la      r8, msg_toobig
        b       fail_common

fail_common:
        cmpeq   p1, r24, zero
        (p1) b  fail_halt
        jal     paint_bg
        jal     con_msg
        st.64   [r24 + 0], zero        # PRESENT (display.md 2)
fail_halt:
        halt

        # paint_bg: fill HEIGHT*STRIDE bytes at the pixel buffer with
        # color r7 (stride is a multiple of 16, display.md 4.3, so a
        # bare st128 loop lands exactly). Clobbers r2-r6.
paint_bg:
        ldz.64  r2, [r24 + 0x10]       # HEIGHT
        ldz.64  r3, [r24 + 0x18]       # STRIDE
        mul     r2, r2, r3
        shl     r4, r7, 32
        or      r4, r4, r7
        shl     r5, r4, 64
        or      r4, r4, r5             # 4 pixels of color
        mov     r5, r25
        add     r6, r25, r2
pb1:
        st128   [r5], r4
        add     r5, r5, 16
        cmpltu  p1, r5, r6
        (p1) b  pb1
        ret

        # con_msg: render the asciiz at r8 in white, 8x16 cells from
        # cell (1,1); '\n' advances the row. Per-pixel predicated
        # stores - dumb and slow, but this path runs once and halts.
        # Chars past the right edge drop (messages are hand-sized to
        # fit anyway). Clobbers r1-r6, r9-r15; preserves r0/r7/r24/r25.
con_msg:
        ldz.64  r15, [r24 + 0x18]      # STRIDE
        li      r10, 1                 # col
        li      r11, 1                 # row
cm_next:
        ldz.8   r1, [r8]
        cmpeq   p1, r1, zero
        (p1) b  cm_out
        add     r8, r8, 1
        cmpeq   p1, r1, 10
        (p1) b  cm_nl
        cmpltu  p1, r1, 0x20
        (p1) b  cm_next
        cmpltu  p1, r1, 0x7F
        (!p1) b cm_next
        ldz.64  r2, [r24 + 0x08]       # WIDTH
        shr     r2, r2, 3
        cmpltu  p1, r10, r2
        (!p1) b cm_next                # off the right edge: drop
        sub     r2, r1, 0x20
        shl     r2, r2, 4
        la      r3, font8x16
        add     r2, r2, r3             # glyph rows
        shl     r3, r11, 4
        mul     r3, r3, r15
        shl     r4, r10, 5
        add     r3, r3, r4
        add     r3, r3, r25            # cell top-left pixel address
        li      r4, 16
cm_row:
        ldz.8   r5, [r2]
        mov     r6, r3
        li      r9, 0x80
        li      r13, 0x00FFFFFF
cm_px:
        and     r14, r5, r9
        cmpeq   p1, r14, zero
        (!p1) st.32 [r6], r13
        add     r6, r6, 4
        shr     r9, r9, 1
        cmpltu  p1, zero, r9
        (p1) b  cm_px
        add     r2, r2, 1
        add     r3, r3, r15
        sub     r4, r4, 1
        cmpltu  p1, zero, r4
        (p1) b  cm_row
        add     r10, r10, 1
        b       cm_next
cm_nl:
        li      r10, 1
        add     r11, r11, 1
        b       cm_next
cm_out:
        ret

# ---------------------------------------------------------------- data

        # The two TX frames, fixed at assemble time (sbp.md SBP-TV-1/
        # TV-3): 14 eth + 20 IP + 8 UDP + 12 SBP + 6 pad = 60. Source
        # MAC bytes 6..11 are zero here and patched from the table at
        # boot; the ACK block field (+50) is patched per block. Both
        # payloads are exactly 12 bytes so the IP header - and its
        # checksum 0x62B5 - is one shared constant; the ROM computes
        # no checksums at runtime (guest UDP checksum 0 is legal,
        # nic.md 6.2 step 5).
        .align 8
req_frame:
        .byte 0x52, 0x55, 0x0A, 0x00, 0x02, 0x02   # dst: peer MAC
        .byte 0x00, 0x00, 0x00, 0x00, 0x00, 0x00   # src: patched
        .byte 0x08, 0x00                           # IPv4
        .byte 0x45, 0x00, 0x00, 0x28, 0x00, 0x00, 0x00, 0x00
        .byte 0x40, 0x11, 0x62, 0xB5               # TTL 64, UDP, csum
        .byte 0x0A, 0x00, 0x02, 0x0F               # 10.0.2.15
        .byte 0x0A, 0x00, 0x02, 0x02               # 10.0.2.2
        .byte 0xB0, 0x07, 0x00, 0x45               # 45063 -> 69
        .byte 0x00, 0x14, 0x00, 0x00               # ulen 20, csum 0
        .byte 0x53, 0x42, 0x50, 0x31               # "SBP1"
        .byte 0x01, 0x00, 0x00, 0x00               # REQ
        .byte 0x00, 0x04, 0x00, 0x00               # max_block 1024
        .byte 0x00, 0x00, 0x00, 0x00, 0x00, 0x00   # pad to 60

        .align 8
ack_frame:
        .byte 0x52, 0x55, 0x0A, 0x00, 0x02, 0x02
        .byte 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
        .byte 0x08, 0x00
        .byte 0x45, 0x00, 0x00, 0x28, 0x00, 0x00, 0x00, 0x00
        .byte 0x40, 0x11, 0x62, 0xB5
        .byte 0x0A, 0x00, 0x02, 0x0F
        .byte 0x0A, 0x00, 0x02, 0x02
        .byte 0xB0, 0x07, 0x00, 0x45
        .byte 0x00, 0x14, 0x00, 0x00
        .byte 0x53, 0x42, 0x50, 0x31
        .byte 0x03, 0x00, 0x00, 0x00               # ACK
        .byte 0x00, 0x00, 0x00, 0x00               # block: patched
        .byte 0x00, 0x00, 0x00, 0x00, 0x00, 0x00

msg_devtab:
        .asciiz "SBROM v1: netboot failed\n\ndevice table validation failed (code BAD1)"
msg_nonic:
        .asciiz "SBROM v1: netboot failed\n\nno NIC (type 4) in the device table (code BAD2)"
msg_notimer:
        .asciiz "SBROM v1: netboot failed\n\nno timer (type 5) in the device table (code BAD3)"
msg_timeout:
        .asciiz "SBROM v1: netboot failed\n\nfetch timed out: no server reply after 5 sends (code BAD4)"
msg_srverr:
        .asciiz "SBROM v1: netboot failed\n\nserver ERR: no boot image configured on the host\n(sahara-gui --serve-image PATH) (code BAD5)"
msg_badimg:
        .asciiz "SBROM v1: netboot failed\n\nbad boot image: SAHIMG01 magic, entry or nsegs invalid (code BAD6)"
msg_badseg:
        .asciiz "SBROM v1: netboot failed\n\nbad boot image: segment truncated or out of bounds (code BAD7)"
msg_toobig:
        .asciiz "SBROM v1: netboot failed\n\nboot image too big for the staging window (code BAD8)"

        # font8x16 follows from font.s (build.sh concatenates it).
