# mmu.s - the identity map (ISA-SPEC 8, SABI 4.4/v0.1 A.1). Built once
# at boot from the device table, immutable after MMU_EN - which is why
# boot's single INVTP is the only one the kernel ever issues.
#
# Static pool: 1 root (shift 8, covers VA < 4 GB) + one shift-0 node
# per touched 16 MB chunk, allocated on first touch. Reference platform
# uses the pool exactly: chunks 0-14 RAM (2 = the user window), 15
# device control windows, 16 pixel buffer. A table needing more chunks
# than the pool holds halts loud (HALT_PTPOOL); a window above the
# root's 4 GB reach halts loud (HALT_PTREACH) - never a silent partial
# map.
#
# The kernel's chunks are S-RWX with U=0; the user window chunk maps
# only what A.2 grants (program pages U+RWX, stack page U+RW) and the
# gap between them stays invalid so wild user pointers fault PF_*.

# ---- mmu_init() -> r0 = root node PA. Builds every mapping the table
# declares. Caller (boot) does mtsr ptbase / invtp / MMU_EN - the
# boot.md 6 step-5 order lives there, visibly.
mmu_init:
        add     sp, sp, -64
        st128   [sp + 48], r29
        st128   [sp + 32], r18
        st128   [sp + 16], r17
        st128   [sp + 0],  r16

        # root node header: shift 8, prefix 0 (bss), prefix_mask = all
        # VPN bits >= 16 (VA bits >= 32) - the map speaks for 4 GB.
        la      r8, mmu_nodes
        li      r9, 8
        st.64   [r8 + 0], r9
        li      r9, -0x10000           # mask lo64: VPN bits 16..63
        st.64   [r8 + 24], r9
        li      r9, 1
        shl     r9, r9, 48
        sub     r9, r9, 1              # mask hi64: VPN bits 64..111
        st.64   [r8 + 32], r9
        add     r9, r8, NODE_SIZE      # bump allocator starts past root
        st.64   [r27 + G_PTNEXT], r9

        # user-window placement checks (SABI v0.1 A.2), before any
        # mapping: a kernel that grew into UBASE or a RAM region too
        # small for the window is a build/config error - halt loud.
        la.abs  r8, _end
        li      r9, UBASE
        cmpleu  p1, r8, r9
        (!p1) b mmu_fail_ublow
        ldz.64  r8, [r27 + G_RAMTOP]
        li      r9, UTOP
        cmpleu  p1, r9, r8
        (!p1) b mmu_fail_ubhigh

        # RAM identity S-RWX, minus the user window chunk: [0, UBASE)
        # and [UTOP, ramtop). What the user window itself maps is A.2's
        # business, below.
        li      r0, 0
        li      r1, UBASE
        li      r2, PTE_R + PTE_W + PTE_X
        jal     mmu_map_range
        li      r0, UTOP
        ldz.64  r1, [r27 + G_RAMTOP]
        sub     r1, r1, r0
        li      r2, PTE_R + PTE_W + PTE_X
        jal     mmu_map_range

        # device control windows S-RW, straight from the table records
        # (base + size fields, boot.md 3.5); the display record also
        # carries the pixel buffer in params[0]/params[1]. Unknown
        # types are skipped whole (boot.md 4.2) - their windows do not
        # exist as far as this kernel is concerned.
        li      r16, DT_BASE
        ldz.64  r17, [r16 + 24]        # ram_region_count
        ldz.64  r18, [r16 + 32]        # device_count
        mul     r17, r17, 32
        add     r16, r16, r17
        add     r16, r16, 40           # -> first device record
mi_dev_loop:
        cmpeq   p1, r18, zero
        (p1) b  mi_dev_done
        ldz.64  r8, [r16 + 0]          # type: 1..4 are known
        cmpeq   p1, r8, zero
        (p1) b  mi_dev_next
        cmpleu  p1, r8, 4
        (!p1) b mi_dev_next
        ldz.64  r9, [r16 + 16]         # base hi: beyond the map's reach
        cmpeq   p1, r9, zero
        (!p1) b mmu_fail_reach
        ldz.64  r0, [r16 + 8]          # base lo
        ldz.64  r1, [r16 + 24]         # window size
        li      r2, PTE_R + PTE_W
        jal     mmu_map_range
        ldz.64  r8, [r16 + 0]
        cmpeq   p1, r8, 1              # display: map the pixel buffer
        (!p1) b mi_dev_next
        ldz.64  r0, [r16 + 32]         # params[0]: pixel buffer PA
        ldz.64  r1, [r16 + 40]         # params[1]: window size
        li      r2, PTE_R + PTE_W
        jal     mmu_map_range
mi_dev_next:
        add     r16, r16, 64
        sub     r18, r18, 1
        b       mi_dev_loop
mi_dev_done:

        la      r0, mmu_nodes          # root PA for the caller's mtsr
        ld128   r16, [sp + 0]
        ld128   r17, [sp + 16]
        ld128   r18, [sp + 32]
        ld128   r29, [sp + 48]
        add     sp, sp, 64
        ret

# ---- mmu_map_range(r0 = base PA, r1 = len bytes, r2 = leaf flags):
# identity-map [base, base+len) rounded out to page granularity.
mmu_map_range:
        add     sp, sp, -64
        st128   [sp + 48], r29
        st128   [sp + 32], r18
        st128   [sp + 16], r17
        st128   [sp + 0],  r16
        add     r17, r0, r1            # end, rounded up
        add     r17, r17, PAGE_SIZE - 1
        and     r17, r17, -PAGE_SIZE
        and     r16, r0, -PAGE_SIZE    # cursor, rounded down
        mov     r18, r2
mr_loop:
        cmpltu  p1, r16, r17
        (!p1) b mr_done
        mov     r0, r16
        mov     r1, r18
        jal     mmu_map_page
        add     r16, r16, PAGE_SIZE
        b       mr_loop
mr_done:
        ld128   r16, [sp + 0]
        ld128   r17, [sp + 16]
        ld128   r18, [sp + 32]
        ld128   r29, [sp + 48]
        add     sp, sp, 64
        ret

# ---- mmu_map_page(r0 = page PA, r1 = leaf flags): one identity leaf.
# Allocates the chunk's shift-0 node on first touch. Leaf entries and
# node headers are stored as low u64 halves - every address here is
# < 4 GB and the bss pool guarantees the high halves are zero.
mmu_map_page:
        shr     r8, r0, 32
        cmpeq   p1, r8, zero
        (!p1) b mmu_fail_reach
        shr     r8, r0, 24
        and     r8, r8, 0xFF           # chunk = root entry index
        la      r9, mmu_nodes
        shl     r10, r8, 4
        add     r10, r10, r9
        add     r10, r10, 64           # -> root entry
        ldz.64  r11, [r10]
        cmpeq   p1, r11, zero
        (!p1) b mp_have
        # first touch: take a node from the pool, write its header
        ldz.64  r12, [r27 + G_PTNEXT]
        la      r13, mmu_nodes_end
        cmpltu  p1, r12, r13
        (!p1) b mmu_fail_pool
        add     r13, r12, NODE_SIZE
        st.64   [r27 + G_PTNEXT], r13
        shr     r13, r0, 16            # prefix = VPN with the low chunk
        and     r13, r13, -256         # bits cleared (shift stays 0)
        st.64   [r12 + 8], r13
        li      r13, -256              # mask lo64: VPN bits 8..63
        st.64   [r12 + 24], r13
        li      r13, 1
        shl     r13, r13, 48
        sub     r13, r13, 1            # mask hi64: VPN bits 64..111
        st.64   [r12 + 32], r13
        or      r11, r12, PTE_TABLE
        st.64   [r10], r11             # link into the root
mp_have:
        and     r11, r11, -64          # child node PA
        shr     r12, r0, 16
        and     r12, r12, 0xFF
        shl     r12, r12, 4
        add     r12, r12, r11
        add     r12, r12, 64           # -> leaf entry
        and     r13, r0, -PAGE_SIZE
        or      r13, r13, r1
        or      r13, r13, PTE_LEAF
        st.64   [r12], r13
        ret

mmu_fail_pool:
        li      r0, HALT_PTPOOL
        halt
mmu_fail_reach:
        li      r0, HALT_PTREACH
        halt
mmu_fail_ublow:
        li      r0, HALT_UBLOW
        halt
mmu_fail_ubhigh:
        li      r0, HALT_UBHIGH
        halt
