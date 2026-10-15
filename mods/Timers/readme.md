# Timers

Goes with **lid-timers.dll**, which brings back the waiting times of the online
game (4.18): crafting and researching parts, and bank, SPLithium tank, prison
and freezer upgrades take time again.

## What this mod changes

The part shop. In the offline game, picking a part whose timer is still
running does nothing. The shop still has the screens that offer Uncle Death's
time skip for it, but nothing led to them. With this mod, picking a running
part opens the time skip:

- **Craft tab**: a part still being crafted.
- **Research tab**: a part still being researched.

Close the time skip without paying and you are back in the list, the timer
still running.

Each part you craft or research is also sent to the game's server straight
away, instead of with the rest when you leave the list. Offline, a part you
had just bought looked free again until then, so buying it a second time on
the same visit made the server refuse it and the game shut down. Now its
countdown shows as soon as you buy it.

And the facility menu (bank, SPLithium tank, prison, freezer). Offline, the
menu marks an upgrade done as soon as it is paid, so it shows the new level
straight away although the upgrade is still waiting. With this mod it reads
the upgrade's real end time, as the online game did: the countdown shows, and
picking the facility while it counts down opens the time skip. (The menu's
skip also asked the server for the wrong timer, so it always answered
"cancelled, already done" and the menu then wrongly showed the upgrade as
finished; this mod fixes that too.)

## What a skip costs

You choose, in the mod's **Configuration** tab (**Skip cost**):

- **1 Death Metal per unit**, the online game's price and the default. Death
  Metals come from the
  [Death Metals](https://github.com/NicoMullin/LiD-Death-Metals) mod.
- **1,000, 2,500, 5,000 or 10,000 Kill Coins per unit**, if you play without
  Death Metals. One Death Metal converts to 5,000 Kill Coins.

The number of units depends on the time left (`master_waiting_reduce`):

| Time left             | Units                         |
|-----------------------|-------------------------------|
| Up to an hour         | 1                             |
| An hour up to a day   | 1, plus 1 for every 5 hours   |
| More than a day       | 6, plus 1 for every 10 hours  |

So a part that takes 15 minutes costs 1 unit, and a 17-day bank upgrade 47.

With Kill Coins, the time-skip screen shows the price in Kill Coins, checks
the Kill Coins you carry and have in the bank (the server takes from both),
and says "You don't have enough Kill Coins." when they don't cover it. The
mod sets the price of `PRD_REDUCE_WAITING_*` in `masters.db` and swaps the
Death Metal sign in the two time-skip messages for the Kill Coin one.

## You also need the plugin

The timers themselves need `lid-timers.dll` in `Binaries\Win64\lid-plugins`
(see the [LiD Timers](https://github.com/NicoMullin/LiD-Timers) page). Without
it nothing has a timer, so this mod never comes into play.

The mod and the plugin are switched together (mod 0.3.2, with LiD DB Editor
0.12.8 or newer): saving with this mod ticked switches `lid-timers.dll` on,
and saving with it unticked switches it off, so the timers stop as well.
Off means renamed to `lid-timers.dll.off`, which the Plugin Loader skips.

## Installing

1. Switch the game's file check off for `BrgGame.upk` (Tools > Hash Patcher)
   if it is not already.
2. Drop this mod onto LiD DB Editor, tick it and click **Save Mod List**.

The `BrgGame.upk` part stacks with other mods that change that file, such as
Death Metals, Stew Multi Pull, Instant Drops and Fighter Class Passives.

## Undo

Untick the mod and save. `lid-timers.dll` is switched off with it (from
LiD DB Editor 0.12.8), so crafting, research and upgrades are instant again.
Picking a running part does nothing again, the
facility menu shows an upgrade as done until you leave and reopen it, and the
time skip costs Death Metals again.
