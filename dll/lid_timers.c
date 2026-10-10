/*
 * lid-timers.dll for Let It Die - a plugin for the LiD Plugin Loader that
 * brings back the waiting times the online game (4.18) had. It changes game
 * code in memory only.
 *
 * The offline game's built-in server still creates every timer the online
 * game had, with the lengths in masters.db:
 *
 *   crafting a part        master_part.init_waiting_minute (+ add per level)
 *   researching a part     master_part_research.init_waiting_minute (+ add)
 *   bank upgrade           master_safe_level.waiting_minute
 *   SPLithium tank upgrade master_spirit_tank_level.waiting_minute
 *   prison upgrade         master_prison.waiting_minute
 *   freezer upgrade        master_freezer.waiting_minute
 *
 * but each time, on the very next instruction, it calls the function that
 * completes a timer at once. That call is what the offline release added. The
 * plugin turns those six calls into "done, success" (mov al,1), so the timer
 * stays and the game's own timer check completes it when its time is really
 * up - the same check the online game used. The one other call of that
 * function, Uncle Death's time skip, is left alone: a skip still completes the
 * timer at once.
 *
 * The time skip had never run offline, and it had a fault: it checks that the
 * timer is running, but then makes a NEW timer from the request (which carries
 * no end time) and charges and completes that one. The time left came out as
 * minus the current time, the price lookup failed and the game shut down. The
 * plugin points that one call at the server's own "find this timer" function
 * instead, so the skip charges for the real time left and completes the
 * running timer.
 *
 * Skipping costs what masters.db says (PRD_REDUCE_WAITING_*): 1 Death Metal
 * per unit as shipped, the online game's price.
 *
 * Safety rules:
 *   - Each piece is found by its exact bytes. The completing function, the
 *     timer-making function, the timer-finding function and the time skip's
 *     make-charge-complete place must each be found exactly once, and the
 *     make-then-complete calls exactly six times, or nothing is changed.
 *   - Changed in the game: seven 5-byte calls, plus a 25-byte stub in a page
 *     of its own.
 *   - No network, no registry. The only file it writes is lid-timers.log next
 *     to itself.
 *   - Delete lid-timers.dll and the game is exactly stock again. Timers that
 *     are running then complete the next time the game checks them.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "version.h"

/* ------------------------------------------------------------------ log */

static wchar_t g_log_path[MAX_PATH];
static int g_log_started;

static void log_line(const char *fmt, ...)
{
    char msg[512];
    SYSTEMTIME t;
    va_list ap;
    int n;
    HANDLE f;
    DWORD written;

    if (!g_log_path[0])
        return;
    GetLocalTime(&t);
    n = snprintf(msg, sizeof msg, "%02u:%02u:%02u  ", t.wHour, t.wMinute, t.wSecond);
    va_start(ap, fmt);
    n += vsnprintf(msg + n, sizeof msg - n - 2, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof msg - 3)
        n = (int)sizeof msg - 3;
    msg[n++] = '\r';
    msg[n++] = '\n';

    /* a fresh log each time the game starts */
    f = CreateFileW(g_log_path, g_log_started ? FILE_APPEND_DATA : GENERIC_WRITE,
                    FILE_SHARE_READ, NULL, g_log_started ? OPEN_ALWAYS : CREATE_ALWAYS,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE)
        return;
    g_log_started = 1;
    WriteFile(f, msg, (DWORD)n, &written, NULL);
    CloseHandle(f);
}

/* ------------------------------------------------------------ helpers */

struct span {
    unsigned char *start;
    size_t size;
};

static int section(unsigned char *base, const char *name, struct span *out)
{
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt;
    IMAGE_SECTION_HEADER *sec;
    WORD i;

    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return 0;
    nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE)
        return 0;
    sec = IMAGE_FIRST_SECTION(nt);
    for (i = 0; i < nt->FileHeader.NumberOfSections; i++, sec++) {
        if (strncmp((const char *)sec->Name, name, IMAGE_SIZEOF_SHORT_NAME) == 0) {
            out->start = base + sec->VirtualAddress;
            out->size = sec->Misc.VirtualSize;
            return 1;
        }
    }
    return 0;
}

/* pattern with a mask: 'x' = must match, '?' = any byte */
static int matches(const unsigned char *p, const unsigned char *pat, const char *mask)
{
    size_t i;
    for (i = 0; mask[i]; i++)
        if (mask[i] == 'x' && p[i] != pat[i])
            return 0;
    return 1;
}

static int find_all(struct span s, const unsigned char *pat, const char *mask, unsigned char **last)
{
    size_t i, n = strlen(mask);
    int hits = 0;
    for (i = 0; i + n <= s.size; i++) {
        if (s.start[i] == pat[0] && matches(s.start + i, pat, mask)) {
            hits++;
            *last = s.start + i;
        }
    }
    return hits;
}

static unsigned char *call_target(unsigned char *call)
{
    int32_t r;
    memcpy(&r, call + 1, 4);
    return call + 5 + r;
}

/* where a rip-relative field points (the instruction ends right after it) */
static unsigned char *rip_target(unsigned char *field)
{
    int32_t r;
    memcpy(&r, field, 4);
    return field + 4 + r;
}

static int write_code(unsigned char *at, const void *bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect(at, n, PAGE_EXECUTE_READWRITE, &old))
        return 0;
    memcpy(at, bytes, n);
    VirtualProtect(at, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, n);
    return 1;
}

/* --------------------------------------------------------- the pieces */

/* Completes a timer at once: push rbx / sub rsp,0x30 / mov rbx,rcx /
 * test rcx,rcx / jne / xor al,al / add rsp,0x30 / pop rbx / ret /
 * mov eax,[rcx+0x10] */
static const unsigned char COMPLETE_START[] = {
    0x40, 0x53, 0x48, 0x83, 0xEC, 0x30, 0x48, 0x8B, 0xD9, 0x48, 0x85, 0xC9, 0x75, 0x08,
    0x32, 0xC0, 0x48, 0x83, 0xC4, 0x30, 0x5B, 0xC3, 0x8B, 0x41, 0x10,
};
static const char COMPLETE_MASK[] = "xxxxxxxxxxxxxxxxxxxxxxxxx";

/* Makes a timer: mov [rsp+8],rbx / push rdi / sub rsp,0x20 / mov rax,[table] /
 * mov rdi,rcx / lea rcx,[table] / mov byte [dirty],1 / call [rax] */
static const unsigned char MAKE_START[] = {
    0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x20,
    0x48, 0x8B, 0x05, 0, 0, 0, 0,
    0x48, 0x8B, 0xF9,
    0x48, 0x8D, 0x0D, 0, 0, 0, 0,
    0xC6, 0x05, 0, 0, 0, 0, 0x01,
    0xFF, 0x10,
};
static const char MAKE_MASK[] = "xxxxxxxxxxxxx????xxxxxx????xx????xxx";

/* Make a timer, then complete it at once: call make / mov rcx,rax /
 * call complete / test al,al */
static const unsigned char SITE_PATTERN[] = {0xE8, 0, 0, 0, 0, 0x48, 0x8B, 0xC8, 0xE8, 0, 0, 0, 0, 0x84, 0xC0};
static const char SITE_MASK[] = "x????xxxx????xx";
#define SITE_CALL_AT   8
#define EXPECTED_SITES 6
#define MAX_SITES      16
#define MAKE_TABLE_AT  23   /* make's lea rcx,[table]: the rip-relative field */

/* Finds a timer in the timer table by kind, part, level and facility:
 * mov [rsp+0x10],rbp / mov [rsp+0x18],rsi / push rdi / sub rsp,0x20 /
 * mov rsi,rdx / mov rbp,rcx / xor edi,edi / mov [rsp+0x30],rbx / nop /
 * test edi,edi / js / cmp edi,[rbp+0x58] / jge / movsxd rbx,edi / mov rdx,rsi /
 * imul rbx,rbx,0x4c / add rbx,[rbp+0x50] / lea rcx,[rbx+8] */
static const unsigned char FIND_START[] = {
    0x48, 0x89, 0x6C, 0x24, 0x10, 0x48, 0x89, 0x74, 0x24, 0x18, 0x57, 0x48, 0x83, 0xEC, 0x20,
    0x48, 0x8B, 0xF2, 0x48, 0x8B, 0xE9, 0x33, 0xFF, 0x48, 0x89, 0x5C, 0x24, 0x30,
    0x0F, 0x1F, 0x40, 0x00, 0x85, 0xFF, 0x78, 0, 0x3B, 0x7D, 0x58, 0x7D, 0,
    0x48, 0x63, 0xDF, 0x48, 0x8B, 0xD6, 0x48, 0x6B, 0xDB, 0x4C, 0x48, 0x03, 0x5D, 0x50,
    0x48, 0x8D, 0x4B, 0x08,
};
static const char FIND_MASK[] = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?xxxx?xxxxxxxxxxxxxxxxxx";

/* "Is this timer still running": lea rcx,[table] / mov rdx,rdi / call find /
 * test rax,rax. Shows the finding function works on the timer table. */
static const unsigned char LOOKUP_CALL[] = {0x48, 0x8D, 0x0D, 0, 0, 0, 0, 0x48, 0x8B, 0xD7,
                                            0xE8, 0, 0, 0, 0, 0x48, 0x85, 0xC0};
static const char LOOKUP_MASK[] = "xxx????xxxx????xxx";

/* The time skip: lea rcx,[rsp+0x30] (the request) / call make / mov rdi,rax /
 * mov rcx,rax / call charge / mov r14d,eax / test eax,eax / jns / (error
 * reply: mov rax,[rbx] / mov rdx,rsi / mov rcx,rbx / call [rax+0x68] / jmp) /
 * mov rcx,rdi / call complete */
static const unsigned char SKIP_PATTERN[] = {
    0x48, 0x8D, 0x4C, 0x24, 0x30, 0xE8, 0, 0, 0, 0, 0x48, 0x8B, 0xF8, 0x48, 0x8B, 0xC8,
    0xE8, 0, 0, 0, 0, 0x44, 0x8B, 0xF0, 0x85, 0xC0, 0x79, 0x0E,
    0x48, 0x8B, 0x03, 0x48, 0x8B, 0xD6, 0x48, 0x8B, 0xCB, 0xFF, 0x50, 0x68, 0xEB, 0,
    0x48, 0x8B, 0xCF, 0xE8, 0, 0, 0, 0,
};
static const char SKIP_MASK[] = "xxxxxx????xxxxxxx????xxxxxxxxxxxxxxxxxxxx?xxxx????";
#define SKIP_MAKE_AT     5
#define SKIP_COMPLETE_AT 45

struct pieces {
    unsigned char *complete, *make, *find, *table, *skip;
    unsigned char *sites[MAX_SITES];
    int nsites, nskips, nlookups;
};

/* Find everything, without changing anything. `base` is the game's exe in
 * memory (the tests pass a mapped copy of it instead). */
static void find_pieces(unsigned char *base, struct pieces *pc)
{
    struct span text;
    size_t i, n = sizeof SITE_PATTERN;

    memset(pc, 0, sizeof *pc);
    if (!section(base, ".text", &text))
        return;
    if (find_all(text, COMPLETE_START, COMPLETE_MASK, &pc->complete) != 1)
        pc->complete = NULL;
    if (find_all(text, MAKE_START, MAKE_MASK, &pc->make) != 1)
        pc->make = NULL;
    if (find_all(text, FIND_START, FIND_MASK, &pc->find) != 1)
        pc->find = NULL;
    if (!pc->complete || !pc->make)
        return;
    pc->table = rip_target(pc->make + MAKE_TABLE_AT);
    for (i = 0; i + n <= text.size; i++) {
        unsigned char *p = text.start + i;
        if (p[0] != 0xE8 || !matches(p, SITE_PATTERN, SITE_MASK))
            continue;
        if (call_target(p) != pc->make || call_target(p + SITE_CALL_AT) != pc->complete)
            continue;
        if (pc->nsites < MAX_SITES)
            pc->sites[pc->nsites] = p + SITE_CALL_AT;
        pc->nsites++;
    }
    for (i = 0; i + sizeof SKIP_PATTERN <= text.size; i++) {
        unsigned char *p = text.start + i;
        if (p[0] != 0x48 || !matches(p, SKIP_PATTERN, SKIP_MASK))
            continue;
        if (call_target(p + SKIP_MAKE_AT) != pc->make || call_target(p + SKIP_COMPLETE_AT) != pc->complete)
            continue;
        pc->skip = p + SKIP_MAKE_AT;
        pc->nskips++;
    }
    if (pc->nskips != 1)
        pc->skip = NULL;
    if (!pc->find)
        return;
    for (i = 0; i + sizeof LOOKUP_CALL <= text.size; i++) {
        unsigned char *p = text.start + i;
        if (p[0] == 0x48 && matches(p, LOOKUP_CALL, LOOKUP_MASK) && rip_target(p + 3) == pc->table &&
            call_target(p + 10) == pc->find)
            pc->nlookups++;
    }
}

/* One page within 2 GB of the game code, for the stub. */
static unsigned char *page_near(unsigned char *code)
{
    const ULONG_PTR step = 0x10000;
    ULONG_PTR origin = (ULONG_PTR)code & ~(step - 1);
    ULONG_PTR d;

    for (d = step; d < 0x70000000; d += step) {
        void *p = VirtualAlloc((void *)(origin - d), 4096, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
        if (!p)
            p = VirtualAlloc((void *)(origin + d), 4096, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
        if (p)
            return p;
    }
    return NULL;
}

/* Point the time skip's "make a timer" call at a stub that finds the running
 * one instead: mov rdx,rcx (the request) / mov rcx,table / mov rax,find /
 * jmp rax. */
static int fix_skip(struct pieces *pc)
{
    unsigned char stub[25], call[5] = {0xE8}, *page;
    intptr_t d;
    int32_t r;

    page = page_near(pc->skip);
    if (!page)
        return 0;
    d = page - (pc->skip + 5);
    if (d != (int32_t)d) {
        VirtualFree(page, 0, MEM_RELEASE);
        return 0;
    }
    stub[0] = 0x48; stub[1] = 0x89; stub[2] = 0xCA;
    stub[3] = 0x48; stub[4] = 0xB9; memcpy(stub + 5, &pc->table, 8);
    stub[13] = 0x48; stub[14] = 0xB8; memcpy(stub + 15, &pc->find, 8);
    stub[23] = 0xFF; stub[24] = 0xE0;
    memcpy(page, stub, sizeof stub);
    FlushInstructionCache(GetCurrentProcess(), page, sizeof stub);
    r = (int32_t)d;
    memcpy(call + 1, &r, 4);
    if (!write_code(pc->skip, call, sizeof call)) {
        VirtualFree(page, 0, MEM_RELEASE);
        return 0;
    }
    return 1;
}

/* ------------------------------------------------------ the changes */

static void patch_game(void)
{
    static const unsigned char success[5] = {0xB0, 0x01, 0x90, 0x90, 0x90};   /* mov al,1 */
    unsigned char *base = (unsigned char *)GetModuleHandleW(NULL);
    struct pieces pc;
    int i, done = 0;

    find_pieces(base, &pc);
    if (!pc.complete || !pc.make || !pc.find) {
        log_line("the timer functions were not found exactly once (complete %s, make %s, find %s) - "
                 "nothing changed. A game update may have moved them.", pc.complete ? "yes" : "NO",
                 pc.make ? "yes" : "NO", pc.find ? "yes" : "NO");
        return;
    }
    if (pc.nsites != EXPECTED_SITES) {
        log_line("found %d places that complete a new timer at once, not %d - nothing changed. "
                 "A game update may have changed them.", pc.nsites, EXPECTED_SITES);
        return;
    }
    /* Without the skip fixed, a skip would shut the game down: all or nothing. */
    if (!pc.skip || pc.nlookups < 1) {
        log_line("the time skip was not found exactly once (found %d, timer lookups %d) - nothing "
                 "changed. A game update may have changed it.", pc.nskips, pc.nlookups);
        return;
    }
    if (!fix_skip(&pc)) {
        log_line("could not fix the time skip - nothing changed");
        return;
    }
    log_line("time skip now charges and completes the running timer (game+0x%llX)",
             (unsigned long long)(pc.skip - base));

    for (i = 0; i < pc.nsites; i++) {
        if (write_code(pc.sites[i], success, sizeof success)) {
            done++;
            log_line("timer kept instead of completed at once (game+0x%llX)",
                     (unsigned long long)(pc.sites[i] - base));
        }
    }
    log_line("ready: %d of %d timers back on", done, EXPECTED_SITES);
}

/* ---------------------------------------------------------------- start */

static int running_in_the_game(void)
{
    wchar_t exe[MAX_PATH];
    const wchar_t *name;
    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH);

    if (n == 0 || n >= MAX_PATH)
        return 0;
    name = wcsrchr(exe, L'\\');
    name = name ? name + 1 : exe;
    return _wcsicmp(name, L"BrgGame-Steam.exe") == 0;
}

#ifndef LID_TIMERS_NO_DLLMAIN
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        wchar_t *slash;
        DWORD n;

        DisableThreadLibraryCalls(inst);
        n = GetModuleFileNameW(inst, g_log_path, MAX_PATH);
        slash = (n && n < MAX_PATH - 24) ? wcsrchr(g_log_path, L'\\') : NULL;
        if (slash)
            wcscpy(slash + 1, L"lid-timers.log");
        else
            g_log_path[0] = 0;

        if (!running_in_the_game())
            return TRUE;    /* some other program - change nothing */
        log_line("LiD Timers lid-timers.dll " LID_DLL_VERSION " loaded");
        patch_game();
    }
    return TRUE;
}
#endif
