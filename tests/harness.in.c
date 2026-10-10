/* Stand-in for BrgGame-Steam.exe: the timer functions, the places that make a
 * timer and complete it at once, and the time skip, in the game's byte shapes.
 * Loads lid-timers.dll from its own folder and checks what it changes. Built
 * with SITES make-then-complete places and the time skip in the game's bytes
 * (SKIP 1) or not (SKIP 0); the plugin must act only on 6 and 1. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define SITES @SITES@
#define SKIP  @SKIP@

/* the timer table: a vtable first, the timers at +0x50, how many at +0x58 */
struct table {
    void **vt;
    unsigned char pad[0x48];
    unsigned char *timers;
    int count;
};
_Static_assert(offsetof(struct table, timers) == 0x50, "timers at +0x50");
_Static_assert(offsetof(struct table, count) == 0x58, "count at +0x58");

int g_completed, g_made;
unsigned char g_dirty, g_timer[0x40], g_running[0x4c];
void *g_completed_what, *g_charged, *g_find_table, *g_find_key, *g_request;
static unsigned char vt_target(void) { return 0; }
static void *g_vt[1] = {(void *)vt_target};
struct table g_table = {g_vt, {0}, g_running, 1};

__asm__(
@ASM@);

typedef unsigned char (*site_fn)(void);
extern unsigned char site0(void), site1(void), site2(void), site3(void), site4(void), site5(void);
extern void skip(void);
static site_fn g_sites[] = {site0, site1, site2, site3, site4,
#if SITES > 5
                            site5,
#endif
};

static int fails;
static void expect(const char *what, int got, int want)
{
    printf("%-55s got %d want %d  %s\n", what, got, want, got == want ? "ok" : "FAIL");
    if (got != want) fails++;
}

/* run every make-then-complete place; how many timers did they complete? */
static int run_sites(int *answers_ok)
{
    int before = g_completed, i, ok = 1;
    for (i = 0; i < SITES; i++)
        ok &= g_sites[i]() == 1;
    *answers_ok = ok;
    return g_completed - before;
}

/* run the time skip; did it make a new timer, and which one did it charge
 * for and complete? 1 = the request's new timer, 2 = the running one */
static void run_skip(int *made, int *charged, int *completed)
{
    g_made = g_completed = 0;
    g_charged = g_completed_what = NULL;
    skip();
    *made = g_made;
    *charged = g_charged == g_request ? 1 : g_charged == g_running ? 2 : 0;
    *completed = g_completed != 1 ? 0 : g_completed_what == g_request ? 1 : g_completed_what == g_running ? 2 : 0;
}

int main(void)
{
    char log[4096] = {0};
    FILE *f;
    int ok, done, made, charged, completed, acts = SITES == 6 && SKIP;

    puts("-- before the plugin");
    done = run_sites(&ok);
    expect("every new timer is completed at once", done, SITES);
    expect("  and each place sees success", ok, 1);
    run_skip(&made, &charged, &completed);
    expect("the time skip makes a new timer", made, 1);
    expect("  and charges for that one", charged, 1);
    expect("  and completes that one", completed, 1);

    if (!LoadLibraryW(L"lid-timers.dll")) { printf("LoadLibrary failed %lu\n", GetLastError()); return 2; }
    f = fopen("lid-timers.log", "rb");
    if (f) { fread(log, 1, sizeof log - 1, f); fclose(f); }
    printf("%s", log);

    puts("-- with the plugin");
    done = run_sites(&ok);
    run_skip(&made, &charged, &completed);
    if (acts) {
        expect("no new timer is completed at once", done, 0);
        expect("  each place still sees success", ok, 1);
        expect("  the log says all six are back", strstr(log, "ready: 6 of 6") != NULL, 1);
        expect("the time skip makes no new timer", made, 0);
        expect("  it looks in the timer table", g_find_table == (void *)&g_table, 1);
        expect("  for the timer the request names", g_find_key == g_request, 1);
        expect("  charges for the running timer", charged, 2);
        expect("  and completes the running timer", completed, 2);
        expect("  the log says the skip is fixed", strstr(log, "time skip now charges") != NULL, 1);
    } else {
        expect("nothing changed: new timers still completed at once", done, SITES);
        expect("  the time skip unchanged too", made == 1 && charged == 1 && completed == 1, 1);
        expect("  the log says so", strstr(log, "nothing changed") != NULL, 1);
    }

    printf(fails ? "\n%d FAILED\n" : "\nall passed\n", fails);
    return fails != 0;
}
