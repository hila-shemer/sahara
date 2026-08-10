# rodata.s - string constants. Follows the generated font.s/keymap.s
# inside the rodata section (SABI 6.2 ordering).

msg_banner:
        .asciiz "Oasis 0.1\n"
msg_prompt:
        .asciiz "$ "
msg_help:
        .asciiz "builtins: help echo uptime halt\n"
msg_unknown:
        .asciiz "unknown command\n"
msg_nl:
        .asciiz "\n"
cmd_help:
        .asciiz "help"
cmd_halt:
        .asciiz "halt"
cmd_uptime:
        .asciiz "uptime"
cmd_echo:
        .asciiz "echo"
cmd_echosp:
        .asciiz "echo "
str_uptime:
        .asciiz "uptime: "
str_ticks:
        .asciiz " ticks, "
str_cycles:
        .asciiz " cycles\n"

        .align 16
__erodata:
