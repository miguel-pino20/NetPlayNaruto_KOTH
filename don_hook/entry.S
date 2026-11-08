/* Preserve the PS2's full 128-bit callee-saved GPRs around o32 C code.
 * LLVM does not assemble R5900 sq/lq, so their encodings are explicit.
 */
.set noreorder
.set noat
.text
.align 4
.macro entry name, target
.globl \name
\name:
    addiu $sp, $sp, -192
    .word 0x7fb00010, 0x7fb10020, 0x7fb20030, 0x7fb30040
    .word 0x7fb40050, 0x7fb50060, 0x7fb60070, 0x7fb70080
    .word 0x7fbc0090, 0x7fbe00a0, 0x7fbf00b0
    jal \target
    nop
    .word 0x7bb00010, 0x7bb10020, 0x7bb20030, 0x7bb30040
    .word 0x7bb40050, 0x7bb50060, 0x7bb60070, 0x7bb70080
    .word 0x7bbc0090, 0x7bbe00a0, 0x7bbf00b0
    jr $ra
    addiu $sp, $sp, 192
.endm
entry np4_poll_entry, np4_poll
entry np4_read_entry, np4_read
.globl np4_read_original
np4_read_original:
    .word 0x0080382d, 0x24030070
    j 0x118e40
    nop
