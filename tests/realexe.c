/* The plugin's search, run on the real BrgGame-Steam.exe (mapped as a file,
 * nothing runs). The timer functions and the time skip must be found exactly
 * once and the make-then-complete places exactly six times. Only run by
 * `build.py --exe PATH`: the game is not part of this repository. */
#define LID_TIMERS_NO_DLLMAIN
#include "../dll/lid_timers.c"

#include <stdio.h>

int main(int argc, char **argv)
{
    static const unsigned long long known[EXPECTED_SITES] = {   /* game build 5.0.4.2 */
        0x115B4F6, 0x115B8C6, 0x115B9F1, 0x115BB53, 0x12F3C0B, 0x1310337};
    static const char *what[EXPECTED_SITES] = {
        "bank upgrade", "SPLithium tank upgrade", "prison upgrade", "freezer upgrade",
        "part research", "part crafting"};
    struct pieces pc;
    unsigned char *base;
    HMODULE m;
    int i, j, fails = 0;

    if (argc < 2) { puts("usage: realexe PATH-TO-BrgGame-Steam.exe"); return 2; }
    m = LoadLibraryExA(argv[1], NULL, LOAD_LIBRARY_AS_IMAGE_RESOURCE | LOAD_LIBRARY_AS_DATAFILE);
    if (!m) { printf("could not map %s (error %lu)\n", argv[1], GetLastError()); return 2; }
    base = (unsigned char *)((ULONG_PTR)m & ~(ULONG_PTR)3);

    find_pieces(base, &pc);
    printf("complete a timer at once  %s game+0x%llX\n", pc.complete ? "found" : "MISSING",
           pc.complete ? (unsigned long long)(pc.complete - base) : 0ULL);
    printf("make a timer              %s game+0x%llX\n", pc.make ? "found" : "MISSING",
           pc.make ? (unsigned long long)(pc.make - base) : 0ULL);
    printf("find a timer              %s game+0x%llX\n", pc.find ? "found" : "MISSING",
           pc.find ? (unsigned long long)(pc.find - base) : 0ULL);
    printf("timer table               game+0x%llX (game build 5.0.4.2: game+0x27D4D3C)\n",
           pc.table ? (unsigned long long)(pc.table - base) : 0ULL);
    printf("time skip                 %d found (needs 1)%s game+0x%llX (5.0.4.2: game+0x1161FD7)\n",
           pc.nskips, pc.skip ? "," : "", pc.skip ? (unsigned long long)(pc.skip - base) : 0ULL);
    printf("timer lookups by find     %d (needs 1 or more)\n", pc.nlookups);
    if (!pc.complete || !pc.make || !pc.find || !pc.skip || pc.nlookups < 1) fails++;
    printf("make-then-complete places %d (needs %d)\n", pc.nsites, EXPECTED_SITES);
    if (pc.nsites != EXPECTED_SITES) fails++;
    for (i = 0; i < pc.nsites && i < MAX_SITES; i++) {
        unsigned long long rva = (unsigned long long)(pc.sites[i] - base);
        const char *name = "moved since 5.0.4.2";
        for (j = 0; j < EXPECTED_SITES; j++)
            if (known[j] == rva) name = what[j];
        printf("  game+0x%llX  %s\n", rva, name);
    }
    printf(fails ? "\n%d FAILED\n" : "\nall found\n", fails);
    return fails != 0;
}
