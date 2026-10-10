"""Write harness.c: the C part from harness.in.c plus generated assembly.

The harness stands in for BrgGame-Steam.exe. Its timer functions, the places
that make a timer and complete it at once, and the time skip are written with
the same machine-code bytes the plugin looks for in the real game.

Usage: python tests/make_harness.py OUTPUT.c [SITES] [SKIP]
SKIP 0 writes the time skip in other bytes, as if a game update had changed it.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITES = int(sys.argv[2]) if len(sys.argv) > 2 else 6
SKIP = int(sys.argv[3]) if len(sys.argv) > 3 else 1


def asm(lines):
    return ''.join('    "%s\\n"\n' % l.replace('"', '\\"') for l in lines)


def b(hexes):
    return '.byte ' + ','.join('0x' + h for h in hexes.split())


code = ['.text',
        # completes a timer at once: counts it, notes which, and answers 1
        '.globl fake_complete', 'fake_complete:',
        b('40 53 48 83 EC 30 48 8B D9 48 85 C9 75 08 32 C0 48 83 C4 30 5B C3 8B 41 10'),
        'incl g_completed(%rip)', 'movq %rbx, g_completed_what(%rip)',
        'movb $1, %al', 'addq $0x30, %rsp', 'popq %rbx', 'ret',
        # makes a timer: counts it and returns its argument as the timer
        '.globl fake_make', 'fake_make:',
        b('48 89 5C 24 08 57 48 83 EC 20 48 8B 05'), '.long g_table - (. + 4)',
        b('48 8B F9 48 8D 0D'), '.long g_table - (. + 4)',
        b('C6 05'), '.long g_dirty - (. + 5)', b('01 FF 10'),
        'incl g_made(%rip)',
        'movq %rdi, %rax', 'movq 0x30(%rsp), %rbx', 'addq $0x20, %rsp', 'popq %rdi', 'ret',
        # finds a timer: notes the table and the key, returns the table's first timer
        '.globl fake_find', 'fake_find:',
        b('48 89 6C 24 10 48 89 74 24 18 57 48 83 EC 20 48 8B F2 48 8B E9 33 FF 48 89 5C 24 30'),
        b('0F 1F 40 00 85 FF 78'), '.byte find_none - (. + 1)',
        b('3B 7D 58 7D'), '.byte find_none - (. + 1)',
        b('48 63 DF 48 8B D6 48 6B DB 4C 48 03 5D 50 48 8D 4B 08'),
        'movq %rbp, g_find_table(%rip)', 'movq %rsi, g_find_key(%rip)', 'movq %rbx, %rax',
        'jmp find_out',
        'find_none:', 'xorl %eax, %eax',
        'find_out:', 'movq 0x30(%rsp), %rbx', 'movq 0x38(%rsp), %rbp', 'movq 0x40(%rsp), %rsi',
        'addq $0x20, %rsp', 'popq %rdi', 'ret',
        # "is this timer still running" (never run, only looked at)
        '.globl fake_lookup', 'fake_lookup:',
        b('48 8D 0D'), '.long g_table - (. + 4)', b('48 8B D7'), 'call fake_find', b('48 85 C0'), 'ret',
        # charges for a skip: notes which timer it was given, answers 0 (paid)
        '.globl fake_charge', 'fake_charge:', 'movq %rcx, g_charged(%rip)', 'xorl %eax, %eax', 'ret']
for i in range(SITES):
    code += [f'.globl site{i}', f'site{i}:', 'subq $0x28, %rsp', 'leaq g_timer(%rip), %rcx',
             'call fake_make', b('48 8B C8'), 'call fake_complete', b('84 C0'),
             'setne %al', 'addq $0x28, %rsp', 'ret']
# the time skip, in the shape of the game's: the request at [rsp+0x30], then
# make / charge / complete. The error reply between them never runs here.
code += ['.globl skip', 'skip:', 'pushq %rbx', 'pushq %rsi', 'pushq %rdi', 'pushq %r14',
         'subq $0x48, %rsp', 'leaq 0x30(%rsp), %rax', 'movq %rax, g_request(%rip)']
if SKIP:
    code += [b('48 8D 4C 24 30'), 'call fake_make', b('48 8B F8 48 8B C8'), 'call fake_charge',
             b('44 8B F0 85 C0 79 0E 48 8B 03 48 8B D6 48 8B CB FF 50 68 EB 00'),
             b('48 8B CF'), 'call fake_complete']
else:
    code += ['leaq 0x30(%rsp), %rcx', 'call fake_make', 'movq %rax, %rdi', 'movq %rax, %rcx',
             'call fake_charge', 'movq %rdi, %rcx', 'call fake_complete']
code += ['addq $0x48, %rsp', 'popq %r14', 'popq %rdi', 'popq %rsi', 'popq %rbx', 'ret']

body = ((HERE / 'harness.in.c').read_text().replace('@ASM@', asm(code))
        .replace('@SITES@', str(SITES)).replace('@SKIP@', str(SKIP)))
Path(sys.argv[1]).write_text(body)
