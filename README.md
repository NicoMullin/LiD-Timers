# LiD Timers

Brings the waiting times back to the offline version of Let It Die (Steam):
crafting and researching parts, and upgrading the bank, the SPLithium tank,
the prison and the freezer take time again, as they did in the online game.

- **lid-timers.dll** (`dll/`): a plugin for the
  [LiD Plugin Loader](https://github.com/NicoMullin/LiD-Plugin-Loader).

## What it does

The offline game's built-in server still makes every timer the online game
had, with the lengths in `masters.db`:

| Timer                  | Length in masters.db                                          |
|------------------------|---------------------------------------------------------------|
| Crafting a part        | `master_part.init_waiting_minute`, + `add_waiting_minute` per level |
| Researching a part     | `master_part_research.init_waiting_minute`, + `add_waiting_minute` per level |
| Bank upgrade           | `master_safe_level.waiting_minute`                            |
| SPLithium tank upgrade | `master_spirit_tank_level.waiting_minute`                     |
| Prison upgrade         | `master_prison.waiting_minute`                                |
| Freezer upgrade        | `master_freezer.waiting_minute`                               |

But each time, straight after making the timer, it completes it. Those six
calls are what the offline release added. The plugin turns them into
"done", so the timer stays, and the game's own timer check completes it when
its time is really up - the same check the online game used.

Uncle Death's time skip completes a timer at once. It costs what `masters.db`
says for `PRD_REDUCE_WAITING_*`: 1 Death Metal per unit as shipped, the online
game's price. The Timers mod in [mods/Timers](mods/Timers) opens the time skip
from the part shop and the facility menu, and can make it cost Kill Coins
instead, for players without Death Metals.

The offline game's time skip had never been used, and it had a fault: it
checked that the timer was running, then made a new, empty timer from the
request and charged for that one. The time left came out hugely negative, the
price lookup failed and the game shut down. The plugin changes that one call to
the server's own "find this timer" function, so the skip charges for the real
time left and completes the running timer.

Safety rules, all in [dll/lid_timers.c](dll/lid_timers.c):

- It only does anything inside `BrgGame-Steam.exe`. Loaded by any other
  program, it changes nothing.
- The timer functions and the time skip must each be found exactly once by
  their exact bytes, and the make-then-complete places exactly six times, or
  nothing is changed. After a game update that moves the code, the plugin does
  nothing and says so in its log.
- Changes are made **in memory only**. The exe on disk is never touched.
- No network, no registry. The only file it writes is `lid-timers.log` next
  to itself.
- Delete `lid-timers.dll` and the game is exactly stock again. Any timer still
  running then completes the next time the game checks it.

## Why the DLL is built by GitHub

A DLL can do anything, so you should not have to take one on trust. Every
release on this page is built by GitHub Actions from the source in this
repository, on GitHub's own machines, and the tests run before anything is
published. You can check the DLL in two ways:

1. **Signed build record.** Each release DLL has an attestation: a signed
   record, kept by GitHub, of the exact workflow run and commit that built it.
   With the [GitHub CLI](https://cli.github.com/):

   ```
   gh attestation verify lid-timers.dll --repo NicoMullin/LiD-Timers
   ```

2. **Rebuild it yourself.** The build is reproducible: the same source and the
   same compiler give a byte-identical file. See
   [Building it yourself](#building-it-yourself) and compare the SHA-256 with
   the one on the release page.

## Installing

**The easy way.** In LiD DB Editor (the LET IT DIE DB Mod Manager) 0.12.6 or
newer, close the game, click **Get mods...** and then **Get** next to
**Timers**. It downloads this repository's newest release, checks it against
the SHA-256 GitHub lists for it, and once you say yes puts the Timers mod in
the manager and `lid-timers.dll` in the game's `Binaries\Win64\lid-plugins` -
with the [LiD Plugin Loader](https://github.com/NicoMullin/LiD-Plugin-Loader)
too, if you do not have it yet. Then switch the game's file check off for
`BrgGame.upk` (Tools > Hash Patcher) if it is not already, tick **Timers** and
click **Save Mod List**.

**By hand.**

1. Install the [LiD Plugin Loader](https://github.com/NicoMullin/LiD-Plugin-Loader)
   once, if you have not already. It puts a `dinput8.dll` and a `lid-plugins`
   folder in the game's `Binaries\Win64` folder.
2. Download `LiD-Timers.zip` from the
   [latest release](https://github.com/NicoMullin/LiD-Timers/releases/latest).
   Put `lid-plugins\lid-timers.dll` from it in the game's `Binaries\Win64\lid-plugins`.
3. In the manager, switch the game's file check off for `BrgGame.upk` (Tools >
   Hash Patcher) if it is not already, drop the `mods\Timers` folder from the
   zip onto it, tick it and click **Save Mod List**.

The release also has `lid-timers.dll` on its own, for anyone who only wants the plugin.

It works alongside other plugins, such as LiD Death Metals and Fighter Class
Passives: they change different parts of the game.

## Building it yourself

You need Windows and Python 3. The compiler is Zig, installed with pip; no
Visual Studio needed.

```
py -3 -m pip install ziglang==0.16.0
py -3 build.py --test
```

The DLL lands in `out\lid-timers.dll` and the SHA-256 is printed at the end.
Use Zig 0.16.0 exactly: another version builds a working DLL, but not a
byte-identical one.

`--test` builds stand-ins for the game exe, with the timer functions and the
make-then-complete places in the game's byte shapes, and checks that:

- with six places, no new timer is completed at once, every place still sees
  success, and the time skip charges for and completes the running timer
  instead of a new one;
- with five places, or with the time skip changed, as after a game update,
  nothing is changed;
- with none of the code, nothing is changed and the log says so.

`--exe PATH\BrgGame-Steam.exe` also runs `tests/realexe.c`: the plugin's own
search on the real game file (mapped, not run), which must find the timer
functions, the time skip and the six places. The game is not in this
repository, so GitHub does not run it.

## Making a release

1. Set the new version in [dll/version.h](dll/version.h).
2. Push a tag with the same version, for example `v0.2.1`.

GitHub builds, tests and publishes the release. The build stops if the tag and
`version.h` don't match.

## License

MIT - see [LICENSE](LICENSE). Made by KSFA.
