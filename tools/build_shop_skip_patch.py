"""Write the shop's time-skip entries for BrgGame.upk as a .PackagePatch.

With lid-timers.dll, crafting and researching a part take time again. In the
part shop, picking an item whose timer is still running does nothing in the
offline game (the online game played a "no" sound). The shop still has the
screens that offer Uncle Death's time skip for it - shop state 7 for crafting,
part shop state 10 for research - but nothing leads to them.

This sends a pick of a running item there:

- BrgUIMenu_ShopBase.TickASync, crafting: SetItemForWaitTimeCancel() (the part
  shop's own helper that marks the picked item; an empty function in the
  other shops), switch the item list off, StartWaitShopState(0.0f, 7).
- BrgUIMenu_PartShop.TickASync, research: switch the item list off,
  StartWait(0.0f, 10).

Those states open the time skip for the item, and come back to the list when
it closes. A skip costs what masters.db says for PRD_REDUCE_WAITING_*.

Each part purchase (crafting: ShopBase.TickASync after OnBuyFinished;
research: PartShop.TickASync after AddResearchPart) is also sent to the server
at once with StartUpdateResearch, so the new timer is in the user data when the
list is rebuilt - see "send each part purchase at once" below.

And in the facility menu (bank, tank, prison, freezer):

- BrgUIMenu_FortTerminal_SubMenu_Facility.SuccessNetWork: after an upgrade is
  paid, read its end time from the waiting list, as the online game did,
  instead of marking it done at once. The menu then shows the countdown and
  offers the time skip, which it already has.
- BrgUIMenu_FortTerminal_SubMenu_Facility.OnTick: the time skip asks for the
  facility's timer with level 1, as the server makes it, instead of 0 (no
  match: "cancelled, already done", and the upgrade shown as finished).

One patch per "Skip cost" choice of the mod, in tfc/cost<N>: cost0 is the
above (Death Metals). The Kill Coin ones (N per unit) also change Uncle
Death's time-skip screen to show, check and report Kill Coins - see
kill_coin_skip() below.

A .PackagePatch holds only the changed functions, not the game's package. LiD
DB Editor applies it to the player's own BrgGame.upk (the format is FCH823's,
from TFC Installer). It names every object and name the new code relies on, so
it is refused, not forced, on a package where any of them moved.

Reads the game's stock BrgGame.upk and never changes it. Needs a LiD DB Editor
checkout for its package reader:

    py -3 tools/build_shop_skip_patch.py --manager PATH/TO/LiD-DB-Editor --upk PATH/TO/BrgGame.upk
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TFC = REPO / "mods" / "Timers" / "tfc"
PATCH_PATH = Path("Game") / "BrgGame" / "CookedPCConsole" / "BrgGame.upk.PackagePatch"
# The mod's "Skip cost" choices: 0 is Death Metals (the game as shipped),
# anything else that many Kill Coins per unit of time skipped. One patch each,
# in tfc/cost<N>.
COSTS = (0, 1000, 2500, 5000, 10000)
HEADER = 48                     # a function's data before its script
REFERENCE_VERSION = 12          # the reference layout TFC Installer writes
SHOP_SIZES = (307, 7507, 5551)          # statements, script bytes in memory, on disk - game 1.89
PART_SIZES = (324, 8689, 6385)
FAC_SIZES = (15, 700, 488)
START_SIZES = (11, 396, 264)
TICK_SIZES = (22, 680, 496)

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--manager", required=True, type=Path, help="a LiD DB Editor checkout")
parser.add_argument("--upk", required=True, type=Path, help="the game's stock BrgGame.upk")
parser.add_argument("--tfc", type=Path, default=TFC, help="where the tfc/cost<N> folders go")
parser.add_argument("--listing", type=Path,
                    help="also write the changed code, disassembled, to this file (one per cost)")
args = parser.parse_args()

sys.path.insert(0, str(args.manager.resolve()))
sys.path.insert(0, str(HERE))
from lid_db_manager.upk import apply as A                   # noqa: E402
from lid_db_manager.upk import package as P                 # noqa: E402
from lid_db_manager.upk import packagepatch as PP           # noqa: E402
from ue3dis import Dis                                      # noqa: E402

raw = args.upk.read_bytes()
print(f"{args.upk.name}: SHA-1 {hashlib.sha1(raw).hexdigest()}")
summary, flat = P.decompressed(raw)
pkg = P.Package(summary, flat, P.read_names(flat, summary), P.read_imports(flat, summary),
                P.read_exports(flat, summary), source=args.upk)
names = lambda i: pkg.names[i].text      # noqa: E731
objs = lambda i: pkg.full_path(i)        # noqa: E731
o = lambda ref: struct.pack("<i", ref)   # noqa: E731
u16 = lambda v: struct.pack("<H", v)     # noqa: E731


def ref_of(path: str) -> int:
    """The object reference (export > 0, import < 0) with this full path."""
    hits = [i + 1 for i in range(len(pkg.exports)) if pkg.full_path(i + 1) == path]
    hits += [-(i + 1) for i in range(len(pkg.imports)) if pkg.full_path(-(i + 1)) == path]
    if len(hits) != 1:
        sys.exit(f"{path}: {len(hits)} matches - is this BrgGame.upk?")
    return hits[0]


def mem_len(chunk: bytes) -> int:
    d = Dis(chunk, names, objs)
    while d.pos < len(chunk):
        d.expr()
    return d.mem


# ------------------------------------------------------------ expression bits
def inst(ref): return b"\x01" + o(ref)
def local(ref): return b"\x00" + o(ref)
def intb(v): return b"\x2c" + bytes([v])
def byte(v): return b"\x24" + bytes([v])
def native(n, *a): return bytes([n]) + b"".join(a) + b"\x16"
def let(a, b): return b"\x0f" + a + b
def eq(a, b): return native(0x9A, a, b)
def cstr(text): return b"\x1f" + text.encode("latin-1") + b"\0"


class Asm:
    """Statements with forward labels; jump targets are memory offsets."""

    def __init__(self):
        self.parts = []

    def code(self, b): self.parts.append(("code", b)); return self
    def label(self, name): self.parts.append(("label", name)); return self
    def jump(self, to): self.parts.append(("jump", to, None)); return self
    def jumpifnot(self, to, cond): self.parts.append(("jumpifnot", to, cond)); return self

    def assemble(self, at: int) -> bytes:
        labels, pos = {}, at
        for p in self.parts:
            if p[0] == "label":
                labels[p[1]] = pos
            elif p[0] == "code":
                pos += mem_len(p[1])
            else:
                pos += 3 + (mem_len(p[2]) if p[2] else 0)
        out = b""
        for p in self.parts:
            if p[0] == "code":
                out += p[1]
            elif p[0] in ("jump", "jumpifnot"):
                to = labels[p[1]] if isinstance(p[1], str) else p[1]
                out += (b"\x06" if p[0] == "jump" else b"\x07") + u16(to) + (p[2] or b"")
        return out


class Fn:
    """One function's script, with code added before its END token."""

    def __init__(self, path, stock_sizes):
        self.ref = ref_of(path)
        self.path = path
        self.data = pkg.export_data(self.ref - 1)
        self.mem, self.disk = struct.unpack_from("<ii", self.data, HEADER - 8)
        self.code = bytearray(self.data[HEADER:HEADER + self.disk])
        self.tail = self.data[HEADER + self.disk:]
        d = Dis(bytes(self.code), names, objs)
        self.lines = d.run()
        if (len(self.lines), self.mem, self.disk) != stock_sizes or self.lines[-1][4] != "END":
            sys.exit(f"{path} is not the one this was written for: {len(self.lines)} statements, "
                     f"{self.mem}/{self.disk} bytes. Is this the stock BrgGame.upk of game 1.89?")
        self.targets = {t for _, _, t in d.targets}
        self.by_mem = {line[1]: line for line in self.lines}
        self.added = b""
        self.added_at = self.mem - 1            # the END token's place
        self.replaced = []

    def stmt(self, at, starts_with):
        line = self.by_mem.get(at)
        if not line or not line[4].startswith(starts_with):
            sys.exit(f"{self.path} @{at:#x}: expected `{starts_with}`, found `{line and line[4]}`")
        return line

    def stmt_bytes(self, at, starts_with):
        d, m, dl, ml, _ = self.stmt(at, starts_with)
        return bytes(self.code[d:d + dl])

    def after(self, at, starts_with):
        _, m, _, ml, _ = self.stmt(at, starts_with)
        return m + ml

    def add(self, asm: Asm) -> int:
        at = self.added_at + mem_len(self.added)
        self.added += asm.assemble(at)
        return at

    def divert(self, at, starts_with, asm: Asm):
        """Replace the statement at `at` with a jump to `asm`, added on the end."""
        d, m, dl, ml, _ = self.stmt(at, starts_with)
        to = self.add(asm)
        refs, extra = divmod(ml - dl, 4)
        pad = dl - 3 - 5 * refs
        if pad < 0 or extra:
            sys.exit(f"{self.path} @{at:#x}: statement too short to replace")
        # an object constant is 4 bytes on disk and 8 in memory, so the filler
        # keeps both sizes of the statement it replaces
        self.code[d:d + dl] = b"\x06" + u16(to) + (b"\x20" + o(0)) * refs + b"\x0b" * pad
        self.replaced.append((m, m + ml))

    def poke_once(self, at, starts_with, old: bytes, new: bytes):
        """Change the one occurrence of `old` in the statement at `at`."""
        d, m, dl, ml, _ = self.stmt(at, starts_with)
        body = bytes(self.code[d:d + dl])
        if body.count(old) != 1 or len(old) != len(new):
            sys.exit(f"{self.path} @{at:#x}: cannot change {old.hex()} here")
        i = d + body.index(old)
        self.code[i:i + len(old)] = new

    def finish(self):
        for lo, hi in self.replaced:
            if any(lo < t < hi for t in self.targets):
                sys.exit(f"{self.path}: a jump lands inside the replaced statement at {lo:#x}")
        code = bytes(self.code[:-1]) + self.added + b"\x53"
        d = Dis(code, names, objs)
        lines = d.run()
        if lines[-1][4] != "END" or d.pos != len(code):
            sys.exit(f"{self.path}: the new script does not read back cleanly")
        starts = {line[1] for line in lines}
        for _, kind, t in d.targets:
            if t not in starts:
                sys.exit(f"{self.path}: a {kind} to {t:#x} does not land on a statement")
        if d.mem > 0xFFFF:
            sys.exit(f"{self.path}: too long for 16-bit jumps")
        self.new_lines = lines
        self.used_names = {i for _, i in d.names}
        self.used_objects = {r for _, r in d.objs if r}
        self.new_data = self.data[:HEADER - 8] + struct.pack("<ii", d.mem, len(code)) + code + self.tail
        print(f"{self.path}: {self.mem}/{self.disk} -> {d.mem}/{len(code)} script bytes (memory/disk)")
        return self.new_data


SB, PS = "BrgUIMenu_ShopBase", "BrgUIMenu_PartShop"
SET_ENABLE = f"I:{SB}.mItemSelect."


def virtual_call(name: str) -> bytes:
    """name() on self, with no parameters."""
    hits = [i for i, n in enumerate(pkg.names) if n.text == name]
    if len(hits) != 1:
        sys.exit(f"{name}: {len(hits)} names - is this BrgGame.upk?")
    return b"\x1b" + struct.pack("<ii", hits[0], 0) + b"\x16"


# ------------------------------------------------ the time skip for Kill Coins
# Uncle Death's time-skip screen (BrgUIMenu_Insurance) works out the cost in
# units (master_waiting_reduce), shows it as Death Metals and refuses when the
# player has fewer. The server charges units x the PRD_REDUCE_WAITING_* price,
# so with the mod's SQL setting that price to N Kill Coins (and 0 Death Metals)
# the screen has to agree:
#
# - GetCurrentUseDeathMetal: the units come back times N. It has no room for a
#   product-price lookup (no local of that type, and a patch cannot add one),
#   so N is written into the code: one patch per choice.
# - Tick_UseDeathMetal: compare with GetKillCoinNumber(), not
#   GetDeathMetalNumber(); when short, show the coin locker's own "You don't
#   have enough Kill Coins." (MSHR_KAIKAN.TXT_NO_KC) instead of the Death Metal
#   shop.
# - NotifyNetworkSuccess: "Completed by spending #0" shows the screen's own
#   figure (mUsing_medal, the Kill Coins) instead of the server's unit count.
#
# The server never reads mUsing_medal; it works the units out itself.
INS = "BrgUIMenu_Insurance"
UNITS_SIZES = (21, 988, 656)
TICK_USE_SIZES = (39, 717, 545)
NOTIFY_SIZES = (44, 1034, 858)
LOCKER_SIZES = (45, 797, 621)
MULTIPLY_QWORD = b"\x62\x28"    # Multiply_SQWordSQWord: native 0x228 in this build (/ is 0x229, + 0x22B)


def int64(v: int) -> bytes:
    return b"\x5b" + struct.pack("<q", v)


def kill_coin_skip(cost: int) -> list[Fn]:
    units = Fn(f"{INS}.GetCurrentUseDeathMetal", UNITS_SIZES)
    num = f"L:{INS}.GetCurrentUseDeathMetal.Num"
    for at in (0x213, 0x328):                       # return Num + fix_add
        ret = units.stmt_bytes(at, f"return N555({num}, ")
        units.divert(at, "return N555(", Asm()
                     .code(b"\x04" + MULTIPLY_QWORD + ret[1:] + int64(cost) + b"\x16"))
    # the last one, `return Num`, is too short to divert: divert the statement
    # before it, which falls through to it, and return from there instead
    num_ref = local(ref_of(f"{INS}.GetCurrentUseDeathMetal.Num"))
    if units.stmt_bytes(0x3C7, f"return {num}") != b"\x04" + num_ref or 0x3C7 in units.targets:
        sys.exit("GetCurrentUseDeathMetal: the last return is not built as expected")
    rounded = units.stmt_bytes(0x38B, f"RoundedUp(L:{INS}.GetCurrentUseDeathMetal.minute, ")
    units.divert(0x38B, "RoundedUp(", Asm()
                 .code(rounded)
                 .code(b"\x04" + MULTIPLY_QWORD + num_ref + int64(cost) + b"\x16"))

    use = Fn(f"{INS}.Tick_UseDeathMetal", TICK_USE_SIZES)
    use.poke_once(0xF3, "jumpifnot 0x141 (N150(GetDeathMetalNumber(), ",
                  virtual_call("GetDeathMetalNumber"), virtual_call("GetKillCoinNumber"))
    locker = Fn(f"{INS}.Tick_ExpandCoinLocker", LOCKER_SIZES)          # only read
    no_kc = locker.stmt_bytes(0x111, f"StartTransition(I:{INS}.mCurrentMenuState, "
                                     "GetNextMenuState(3, 'MSHR_KAIKAN.TXT_NO_KC'")
    sub3 = intb(3) + cstr("MSHR_KAIKAN.TXT_NO_KC")
    if no_kc.count(sub3) != 1:
        sys.exit("Tick_ExpandCoinLocker: the Kill Coin message is not built as expected")
    no_kc = no_kc.replace(sub3, intb(2) + cstr("MSHR_KAIKAN.TXT_NO_KC"))   # 2: message, then close
    use.stmt(0x13E, "jump 0x1d6")
    use.divert(0x120, f"StartTransition(I:{INS}.mCurrentMenuState, GetBuyDeathMetalMenuState(", Asm()
               .code(no_kc)
               .jump(0x1D6))

    # mUsing_medal, as Tick_UseDeathMetal reads it: (I:mWaitTimeParam).mUsing_medal
    check = use.stmt_bytes(0xF3, "jumpifnot 0x141 (")
    param = inst(ref_of(f"{INS}.mWaitTimeParam"))
    at = check.find(b"\x38\x4a\x35")
    using = check[at + 2:at + 2 + 11 + len(param)]
    if at < 0 or not using.endswith(param):
        sys.exit("Tick_UseDeathMetal: mUsing_medal is not read as expected")
    notify = Fn(f"{INS}.NotifyNetworkSuccess", NOTIFY_SIZES)
    done = notify.stmt_bytes(0x25D, f"StartTransition(I:{INS}.mCurrentMenuState, "
                                    "GetNextMenuState(2, 'TIME_CRUNCH.TXT_DONE'")
    res = inst(ref_of(f"{INS}.mWaitRes"))
    at = done.find(b"\x38\x53\x19" + res)
    used = done[at:at + 20]
    if at < 0 or done.count(used) != 1:
        sys.exit("NotifyNetworkSuccess: mUsed_medal is not read as expected")
    notify.stmt(0x2B6, "cast<BrgGameInfo>(")
    notify.divert(0x25D, "StartTransition(", Asm()
                  .code(done.replace(used, using))
                  .jump(0x2B6))
    return [units, use, notify]


def functions_for(cost: int) -> list[Fn]:
    """Every changed function, for one "Skip cost" choice."""
    # ----------------------------------------------------- crafting: ShopBase state 7
    shop = Fn(f"{SB}.TickASync", SHOP_SIZES)
    shop.stmt(0x1118, "jumpifnot 0x115a (N130(N153(" + SET_ENABLE)       # running and not at the buy limit
    off = shop.stmt_bytes(0x1188, SET_ENABLE)
    if "SetEnableSelect(false" not in shop.stmt(0x1188, SET_ENABLE)[4]:
        sys.exit("ShopBase.TickASync: the item-list switch is not where expected")
    to_state = bytearray(shop.stmt_bytes(0x1566, f"F:{SB}.StartWaitShopState(0.0f, 9b)"))
    if to_state[-3:] != byte(9) + b"\x16":
        sys.exit("ShopBase.TickASync: StartWaitShopState is not built as expected")
    to_state[-2] = 7
    shop.divert(0x1157, "jump 0x129d", Asm()
                .code(virtual_call("SetItemForWaitTimeCancel"))
                .code(off)
                .code(bytes(to_state))
                .jump(0x129D))

    # ---------------------------------------------------- research: PartShop state 10
    part = Fn(f"{PS}.TickASync", PART_SIZES)
    part.stmt(0x1151, "jumpifnot 0x1182 (N153(" + SET_ENABLE)            # running
    off = part.stmt_bytes(0x11B0, SET_ENABLE)
    wait = bytearray(part.stmt_bytes(0x11D1, "StartWait(0.0f, 11)"))
    if wait[-3:] != intb(11) + b"\x16":
        sys.exit("PartShop.TickASync: StartWait is not built as expected")
    wait[-2] = 10
    part.divert(0x117F, "jump 0x120e", Asm()
                .code(off)
                .code(bytes(wait))
                .jump(0x120E))

    # --------------------------------------- send each part purchase at once
    # The shop collects purchases (mDbUserShopHistorys) and sends them in one
    # Update_research when the list is left. After a buy the online game marked
    # the part busy with its craft or research time, worked out from the
    # part's waiting minutes; offline marks it with 0 (and the package no
    # longer references the waiting-minute fields, so that cannot come back).
    # The part then looks free, a second buy of it goes into the same batch,
    # the server refuses it ("receiveResearchPart need waiting", 355) and the
    # game shuts down. Sending the purchase straight away puts the real timer
    # into the user data, and the list that is rebuilt next (crafting: shop
    # state 5; research: part shop state 8) shows its countdown from there.
    send = shop.stmt_bytes(0x1247, "StartUpdateResearch(GetAdjustShopState(8b))")
    if not send.endswith(byte(8) + b"\x16\x16"):
        sys.exit("ShopBase.TickASync: StartUpdateResearch is not built as expected")
    shop.stmt(0x148D, "jump 0x1d50")
    shop.divert(0x147C, f"F:{SB}.StartWaitShopState(0.0f, 5b)", Asm()          # after a buy
                .code(send[:-4] + byte(5) + b"\x16\x16")       # StartUpdateResearch(GetAdjustShopState(5))
                .jump(0x148D))
    part.stmt(0x1390, f"F:{PS}.AddResearchPart()")
    part.stmt(0x13AB, "jump 0x21ee")
    part.divert(0x139A, "StartWait(0.0f, 8)", Asm()                             # after a research
                .code(send[:9] + intb(8) + b"\x16")            # StartUpdateResearch(8)
                .jump(0x13AB))

    # -------------------------------- facilities: the end time after paying an upgrade
    # Offline, SuccessNetWork marks the upgrade done at once (mPeriod = -1). The
    # online game read the timer's end time from the waiting list there, as Start
    # does when the menu opens. Start's statement, for the picked facility:
    FAC = "BrgUIMenu_FortTerminal_SubMenu_Facility"
    fac = Fn(f"{FAC}.SuccessNetWork", FAC_SIZES)
    start = Fn(f"{FAC}.Start", START_SIZES)                 # only read
    pick = f"(I:{FAC}.mFacilityParams["
    line = start.stmt(0xB9, pick + f"L:{FAC}.Start.Count]).")
    if f"= F:{FAC}.GetWaitEndTime(" not in line[4]:
        sys.exit("Facility.Start: the end-time read is not where expected")
    read_end = start.stmt_bytes(0xB9, pick)
    count, picked = local(ref_of(f"{FAC}.Start.Count")), inst(ref_of(f"{FAC}.mSelectFacilityIndex"))
    if read_end.count(count) != 2:
        sys.exit("Facility.Start: the end-time read is not built as expected")
    read_end = read_end.replace(count, picked)
    stock = fac.stmt_bytes(0x13D, pick + f"I:{FAC}.mSelectFacilityIndex]).")
    if stock[-9:] != b"\x5b" + b"\xff" * 8 or not read_end.startswith(stock[:-9]):
        sys.exit("Facility.SuccessNetWork: `mPeriod = -1` is not built as expected")
    fac.divert(0x13D, pick, Asm()
               .code(read_end)
               .jump(0x16D))

    # The time skip for a facility sends no level (0), but the server makes every
    # facility timer with level 1 and looks a timer up by kind, part, level and
    # facility. With 0 it finds none, answers 356 "already done", and the menu then
    # shows the upgrade as finished while it is still running. Send 1.
    tick = Fn(f"{FAC}.OnTick", TICK_SIZES)
    call = "I:BrgUIBase.mUIManager.I:BrgUIManager.mInsuranceMenu.InitializeUseDeathMetal("
    if call not in tick.stmt(0x6C, "I:BrgUIBase.mUIManager.")[4].replace("{skip=0x9,BrgUIManager.mInsuranceMenu,0}", "") \
            .replace("{skip=0x6a,None,0}", ""):
        sys.exit("Facility.OnTick: the time skip call is not where expected")
    EMPTY, ONE = b"\x4a", b"\x26"
    tick.poke_once(0x6C, "I:BrgUIBase.mUIManager.", cstr("RESEARCHFACILITY") + EMPTY + EMPTY,
                   cstr("RESEARCHFACILITY") + EMPTY + ONE)

    functions = [shop, part, fac, tick]
    if cost:
        functions += kill_coin_skip(cost)
    for fn in functions:
        fn.finish()
    return functions


# -------------------------------------------------------------------- the patch
def fstring(text: str) -> bytes:
    encoded = text.encode("latin-1") + b"\0"
    return struct.pack("<i", len(encoded)) + encoded


def class_of(ref: int) -> tuple[str, str]:
    if ref < 0:
        imp = pkg.imports[-ref - 1]
        return pkg.name(imp.class_name, imp.class_name_number), \
            pkg.name(imp.class_package, imp.class_package_number)
    class_index = pkg.exports[ref - 1].class_index
    return (pkg.object_name(class_index) if class_index else "Class"), ""


def path_of(ref: int) -> str:
    return pkg.full_path(ref).replace(".", "\\")


def write_patch(functions: list[Fn], out_path: Path) -> None:
    """Write the .PackagePatch, after checking that applying it gives what it should."""
    used_objects = {fn.ref for fn in functions}
    used_names = set()
    for fn in functions:
        used_objects |= fn.used_objects
        used_names |= fn.used_names
    object_refs = sorted(used_objects, key=lambda r: (r < 0, abs(r)))
    name_refs = sorted(used_names)

    out = bytearray()
    out += struct.pack("<i", 2)
    for table in (pkg.names, pkg.imports, pkg.exports):
        out += struct.pack("<ii", len(table), 0)
    out += struct.pack("<i", len(functions))
    for fn in functions:
        out += struct.pack("<ii", fn.ref - 1, 0)
        out += struct.pack("<i", len(fn.new_data)) + fn.new_data
    out += struct.pack("<i", REFERENCE_VERSION)
    out += struct.pack("<i", len(name_refs))
    for i in name_refs:
        out += struct.pack("<i", i) + fstring(pkg.names[i].text)
    out += struct.pack("<i", len(object_refs))
    for ref in object_refs:
        class_name, class_package = class_of(ref)
        out += struct.pack("<i", ref) + fstring(path_of(ref))
        if ref < 0:
            out += fstring(path_of(ref))
        out += fstring(class_name)
        if ref < 0:
            out += fstring(class_package)
    patch_bytes = bytes(out)

    # ----------------------------------------------------- check it before writing it
    patch = PP.read(patch_bytes)
    fresh = P.Package(summary, flat, pkg.names, pkg.imports, P.read_exports(flat, summary), source=args.upk)
    if A.problems(fresh, patch):
        sys.exit("the patch does not fit: " + "; ".join(A.problems(fresh, patch)))
    applied, _ = A.apply(fresh, patch)
    expected = bytearray(flat)
    entries = P.read_exports(flat, summary)
    for fn in functions:
        # no bigger: written over the old one in place; bigger: added on the end
        e = entries[fn.ref - 1]
        old_at, old_size, new = e.serial_offset, e.serial_size, fn.new_data
        if len(new) <= old_size:
            expected[old_at:old_at + old_size] = new + bytes(old_size - len(new))
            at = old_at
        else:
            expected[old_at:old_at + old_size] = bytes(old_size)
            at = len(expected)
            expected += new
        A._place_entry(expected, e, at, len(new))
    if applied != bytes(expected):
        sys.exit("applying the patch does not give the expected package")
    re_exports = P.read_exports(applied, summary)
    for fn in functions:
        e = re_exports[fn.ref - 1]
        if bytes(applied[e.serial_offset:e.serial_offset + e.serial_size]) != fn.new_data:
            sys.exit(f"{fn.path}: not where its export entry says")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(patch_bytes)
    print(f"checks {len(name_refs)} name(s), {len(object_refs)} object(s); wrote {out_path} "
          f"({len(patch_bytes):,} bytes), SHA-256 {hashlib.sha256(patch_bytes).hexdigest()}")


def write_listing(functions: list[Fn], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for fn in functions:
            f.write(f"# {fn.path}\n")
            changed = {m for m, _ in fn.replaced}
            for d, m, dl, ml, t in fn.new_lines:
                if m >= fn.added_at or m in changed:
                    f.write(f"{m:04x} {t}\n")


for cost in COSTS:
    print(f"--- skip cost: {cost or 'Death Metals'}{' KC per unit' if cost else ''}")
    functions = functions_for(cost)
    write_patch(functions, args.tfc / f"cost{cost}" / PATCH_PATH)
    if args.listing:
        write_listing(functions, args.listing.with_name(f"{args.listing.stem}-cost{cost}{args.listing.suffix}"))
