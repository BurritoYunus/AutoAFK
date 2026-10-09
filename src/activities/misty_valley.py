"""Misty Valley event

Clears the Misty Valley stages from wherever the map opens, up to stage 20.

For every stage it reads the Silver and Gold challenges from the stage window
and builds a team with the in-game faction and class filters, always taking the
strongest heroes (top-left first):

* Silver is always "Win with 4 <faction> heroes".
* Gold challenges that only need a win (time limits, no deaths, ultimates)
  are done by any win.
* Team-shape Gold challenges (5 factions, frontline Tank, backline Ranger,
  same class, no Ranger/Mage, no Tank/Mage) are combined with Silver in one
  team when possible, otherwise done in a separate battle.
* "Victorious Team Contains" (specific heroes) is skipped.

The run stops after stage 20, or at a stage that shows an "Opens:" timer.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.activities.base_activity import BaseActivity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Game data and screen layout (1080x1920)
# ---------------------------------------------------------------------------

FACTIONS = ['lightbearer', 'mauler', 'wilder', 'graveborn',
            'celestial', 'hypogean', 'dimensional', 'draconis']
CLASSES = ['warrior', 'tank', 'ranger', 'mage', 'support']
ALL = 'all'

SILVER_GROUPS = {
    'lightbearer': ['lightbearer'],
    'mauler': ['mauler'],
    'wilder': ['wilder'],
    'graveborn': ['graveborn'],
    'chd': ['celestial', 'hypogean', 'dimensional'],
}

# Gold challenges that need a particular team shape
CONSTRAINT_GOLDS = {'factions5', 'frontline_tank', 'backline_ranger', 'same_class',
                    'no_ranger_mage', 'no_tank_mage'}
# Gold challenges any win completes (the team is strong enough)
WIN_GOLDS = {'ultimate', 'defeat_within', 'no_dying', 'win_within', 'unknown'}
# Gold challenges the bot can't do
SKIP_GOLDS = {'victorious'}

LAST_STAGE = 20
MAX_ATTEMPTS_PER_STAGE = 4

# Formation screen
FACTION_Y = 1678
FACTION_X = {ALL: 180, 'lightbearer': 283, 'mauler': 386, 'wilder': 489, 'graveborn': 592,
             'celestial': 696, 'hypogean': 800, 'dimensional': 904, 'draconis': 1008}
CLASS_Y = 1467
CLASS_X = {ALL: 180, 'warrior': 282, 'tank': 385, 'ranger': 488, 'mage': 592, 'support': 695}
CARD_XS = [130, 333, 535, 737, 940]
CARD_Y = 1250
PANEL_EXPAND = (72, 1680)       # "^" when the filter panel is collapsed
REMOVE_ALL = (1025, 1105)
FORMATION_BATTLE = (540, 1830)
FORMATION_BACK = (60, 1830)

# Stage window
STAGE_BATTLE = (540, 1580)
STAGE_CLOSE = (990, 340)
STAMP_ROWS = {'stone': (540, 740), 'silver': (760, 965), 'gold': (980, 1185)}

# Map
HUT_TAP_OFFSET = (0, 0)
MAP_TOP, MAP_BOTTOM = 230, 1700


# ---------------------------------------------------------------------------
# Team planning (pure logic, no screen access)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """One hero to place: try factions in order, and classes in order for each"""
    factions: Tuple[str, ...]
    classes: Tuple[str, ...] = (ALL,)
    distinct: bool = False   # pick a faction not used yet in this team


def _slots(n, factions, classes=(ALL,)):
    return [Slot(tuple(factions), tuple(classes))] * n


def silver_plan(group: str) -> List[Slot]:
    """4 heroes of the group + the strongest hero of another faction"""
    g = SILVER_GROUPS[group]
    other = [f for f in FACTIONS if f not in g]
    return _slots(4, g) + _slots(1, other + g)


def any_plan() -> List[Slot]:
    return _slots(5, [ALL])


def gold_plans(kind: str) -> List[List[Slot]]:
    """Plans for a Gold challenge on its own"""
    non_ranger = ['warrior', 'tank', 'mage', 'support']
    if kind == 'factions5':
        return [[Slot(tuple(FACTIONS), (ALL,), distinct=True)] * 5]
    if kind == 'frontline_tank':
        return [_slots(2, [ALL], ['tank']) + _slots(3, [ALL])]
    if kind == 'backline_ranger':
        return [_slots(2, [ALL], non_ranger + ['ranger']) + _slots(3, [ALL], ['ranger'])]
    if kind == 'same_class':
        return [_slots(5, [ALL], [c]) for c in CLASSES]
    if kind == 'no_ranger_mage':
        return [_slots(5, [ALL], ['warrior', 'tank', 'support'])]
    if kind == 'no_tank_mage':
        return [_slots(5, [ALL], ['warrior', 'ranger', 'support'])]
    return []


def combined_plans(group: str, kind: str) -> List[List[Slot]]:
    """Plans that satisfy Silver and a team-shape Gold in one battle"""
    g = SILVER_GROUPS[group]
    other = [f for f in FACTIONS if f not in g]
    non_ranger = ['warrior', 'tank', 'mage', 'support']
    if kind == 'frontline_tank':
        return [_slots(2, g, ['tank']) + _slots(2, g) + _slots(1, other)]
    if kind == 'backline_ranger':
        # Front can be anything; prefer non-Rangers there so Rangers are left for the back
        return [_slots(2, g, non_ranger + ['ranger']) + _slots(2, g, ['ranger']) + _slots(1, other, ['ranger'])]
    if kind == 'same_class':
        return [_slots(4, g, [c]) + _slots(1, other, [c]) for c in CLASSES]
    if kind == 'no_ranger_mage':
        allowed = ['warrior', 'tank', 'support']
        return [_slots(4, g, allowed) + _slots(1, other, allowed)]
    if kind == 'no_tank_mage':
        allowed = ['warrior', 'ranger', 'support']
        return [_slots(4, g, allowed) + _slots(1, other, allowed)]
    return []   # factions5 can't be combined with "4 of one faction"


@dataclass
class StageInfo:
    number: int
    stone_done: bool
    silver_done: bool
    gold_done: bool
    silver_kind: Optional[str]
    gold_kind: Optional[str]
    timer: bool
    playable: bool


@dataclass
class StageMemory:
    attempts: int = 0
    silver_impossible: bool = False
    gold_impossible: bool = False


@dataclass
class BattlePlan:
    label: str
    plans: List[List[Slot]]
    # what to mark impossible if none of the plans can be built
    covers_silver: bool = False
    covers_gold: bool = False
    fallback_any: bool = False   # if nothing can be built, still try a plain win


def next_battle(info: StageInfo, mem: StageMemory) -> Optional[BattlePlan]:
    """Decide the next battle for a stage, or None if it's finished"""
    silver_needed = (not info.silver_done and info.silver_kind in SILVER_GROUPS
                     and not mem.silver_impossible)
    gold_needed = not info.gold_done and info.gold_kind not in SKIP_GOLDS
    gold_constraint = gold_needed and info.gold_kind in CONSTRAINT_GOLDS and not mem.gold_impossible
    gold_win = gold_needed and (info.gold_kind in WIN_GOLDS or info.gold_kind is None)
    stone_needed = not info.stone_done

    if not (silver_needed or gold_constraint or gold_win or stone_needed):
        return None
    if mem.attempts >= MAX_ATTEMPTS_PER_STAGE:
        return None

    if silver_needed and gold_constraint:
        plans = combined_plans(info.silver_kind, info.gold_kind) + [silver_plan(info.silver_kind)]
        return BattlePlan('Silver + Gold', plans, covers_silver=True, fallback_any=stone_needed)
    if silver_needed:
        return BattlePlan('Silver', [silver_plan(info.silver_kind)], covers_silver=True,
                          fallback_any=stone_needed)
    if gold_constraint:
        return BattlePlan('Gold', gold_plans(info.gold_kind), covers_gold=True,
                          fallback_any=stone_needed)
    # Only a plain win is left (Stone and/or a win-type Gold)
    plans = [silver_plan(info.silver_kind)] if info.silver_kind in SILVER_GROUPS else []
    return BattlePlan('Win', plans + [any_plan()])


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

class MistyValleyActivities(BaseActivity):
    """Runs the Misty Valley event"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tpl_cache: Dict[Tuple[str, bool], np.ndarray] = {}
        self._stop_event = None
        self._pause_event = None
        self._faction: Optional[str] = None
        self._class: str = ALL   # the class filter starts on ALL

    # -- template helpers -------------------------------------------------

    def _tpl(self, name: str, gray: bool = True) -> Optional[np.ndarray]:
        key = (name, gray)
        if key not in self._tpl_cache:
            path = os.path.join(self.image.img_dir, f'{name}.png')
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
            if img is None:
                logger.debug(f"Template missing: {path}")
            self._tpl_cache[key] = img
        return self._tpl_cache[key]

    def _shot(self):
        """Screenshot as (BGR, gray) numpy arrays"""
        pil = self.device.get_screenshot().convert('RGB')
        bgr = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        return bgr, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    def _score(self, scr: np.ndarray, name: str, region=None, gray=True) -> Tuple[float, Tuple[int, int]]:
        """Best match score and centre of a template"""
        tpl = self._tpl(name, gray)
        if tpl is None:
            return 0.0, (0, 0)
        ox = oy = 0
        if region:
            x, y, w, h = region
            scr = scr[max(y, 0):y + h, max(x, 0):x + w]
            ox, oy = max(x, 0), max(y, 0)
        if scr.shape[0] < tpl.shape[0] or scr.shape[1] < tpl.shape[1]:
            return 0.0, (0, 0)
        res = cv2.matchTemplate(scr, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        return float(mx), (loc[0] + ox + tpl.shape[1] // 2, loc[1] + oy + tpl.shape[0] // 2)

    def _all(self, scr: np.ndarray, name: str, threshold: float, region=None,
             min_dist: int = 40) -> List[Tuple[int, int, float]]:
        """All matches of a template as (x, y, score), strongest first"""
        tpl = self._tpl(name, True)
        if tpl is None:
            return []
        ox = oy = 0
        if region:
            x, y, w, h = region
            scr = scr[y:y + h, x:x + w]
            ox, oy = x, y
        res = cv2.matchTemplate(scr, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        found: List[Tuple[int, int, float]] = []
        for yy, xx in sorted(zip(ys, xs), key=lambda p: -res[p[0], p[1]]):
            cx, cy = xx + ox + tpl.shape[1] // 2, yy + oy + tpl.shape[0] // 2
            if all(abs(cx - fx) > min_dist or abs(cy - fy) > min_dist for fx, fy, _ in found):
                found.append((cx, cy, float(res[yy, xx])))
        return found

    def _visible(self, name: str, threshold: float = 0.8, region=None, gray: bool = True) -> bool:
        _, g = self._shot()
        return self._score(g, name, region)[0] >= threshold

    def _wait_for(self, name: str, timeout: float, threshold: float = 0.8, region=None,
                  interval: float = 0.5) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._stopped():
                return False
            if self._visible(name, threshold, region):
                return True
            time.sleep(interval)
        return False

    def _stopped(self) -> bool:
        if self._pause_event is not None:
            while self._pause_event.is_set() and not (self._stop_event and self._stop_event.is_set()):
                time.sleep(0.5)
        return bool(self._stop_event and self._stop_event.is_set())

    # -- entering the event ----------------------------------------------

    def _on_map(self) -> bool:
        return self._visible('labels/misty/map_title', 0.8, (300, 20, 480, 100))

    def enter(self) -> bool:
        """Campaign -> Events -> Adventure -> Misty Valley -> Continue Adventure"""
        logger.info("    Opening Misty Valley")
        self.controller.confirm_location('campaign')
        self.controller.expand_menus()
        if not self.image.click_image('buttons/events', confidence=0.8, retry=3, seconds=3, suppress=True):
            logger.warning("    Events button not found")
            return False
        # Adventure tab, then the Misty Valley banner
        if not self.image.click_image('labels/misty/entry_adventure', confidence=0.7, retry=2,
                                      seconds=2, suppress=True, region=(300, 1700, 400, 219)):
            self.controller.tap(490, 1830, seconds=2)
        if not self.image.click_image('labels/misty/entry_event_banner', confidence=0.7, retry=3,
                                      seconds=4, suppress=True):
            self.controller.tap(540, 400, seconds=4)
        # World map: tap the Misty Valley flag (above its label)
        if not self.image.click_image('labels/misty/entry_world_icon', confidence=0.7, retry=3,
                                      seconds=2, suppress=True, xyshift=(0, -90)):
            self.controller.tap(540, 990, seconds=2)
        if not self.image.click_image('labels/misty/entry_continue', confidence=0.7, retry=3,
                                      seconds=2, suppress=True):
            self.controller.tap(540, 1525, seconds=2)
        if self._wait_for('labels/misty/map_title', timeout=20, region=(300, 20, 480, 100)):
            self.wait(2)   # let the camera settle on the cart
            return True
        if not self._stopped():
            logger.error("    Misty Valley map not found")
        return False

    def reenter(self) -> bool:
        self.controller.recover(silent=True)
        return self.enter()

    # -- map ---------------------------------------------------------------

    def _stage_huts(self, gray) -> List[Tuple[int, int]]:
        """Stage positions on screen, bottom first"""
        huts = self._all(gray, 'buttons/misty/stage_hut', 0.85)
        huts = [(x, y) for x, y, _ in huts if MAP_TOP < y < MAP_BOTTOM]
        return sorted(huts, key=lambda p: -p[1])

    def _gates(self, gray) -> List[Tuple[int, int, bool]]:
        """Gates on screen as (x, y, is_open), top first"""
        found: List[Tuple[int, int, float]] = []
        for name in ('buttons/misty/gate_beam', 'buttons/misty/gate_beam_closed'):
            for x, y, s in self._all(gray, name, 0.75):
                if all(abs(x - fx) > 60 or abs(y - fy) > 40 for fx, fy, _ in found):
                    found.append((x, y, s))
        gates = []
        for x, y, _ in found:
            door, _ = self._score(gray, 'labels/misty/gate_door', (x - 70, y + 50, 140, 120))
            gates.append((x, y, door < 0.75))
        return sorted(gates, key=lambda g: g[1])

    def _scroll_up(self) -> None:
        """Show the next stage up: tap the highest open gate, or drag the map"""
        _, gray = self._shot()
        open_gates = [(x, y) for x, y, is_open in self._gates(gray) if is_open and y > MAP_TOP]
        if open_gates:
            x, y = open_gates[0]
            logger.debug(f"    Tapping open gate at ({x}, {y})")
            self.controller.tap(x, y + 60, seconds=3)
        else:
            self.controller.swipe(540, 600, 540, 1400, duration=700, seconds=2)

    # -- stage window ------------------------------------------------------

    def _in_stage_window(self, gray) -> bool:
        return self._score(gray, 'labels/misty/completion_req', (280, 450, 520, 100))[0] >= 0.8

    def _stage_number(self, gray) -> Optional[int]:
        """Stage number from the window title (binarised text comparison)"""
        mask = gray > 200
        best, best_n = 1.0, None
        for n in range(1, LAST_STAGE + 1):
            tpl = self._tpl(f'labels/misty/title_{n:02d}')
            if tpl is None:
                continue
            t = tpl > 200
            h, w = t.shape
            for dy in range(-5, 6):
                for dx in range(-5, 6):
                    c = mask[355 + dy:355 + dy + h, 420 + dx:420 + dx + w]
                    if c.shape != t.shape:
                        continue
                    score = (c ^ t).sum() / max((c | t).sum(), 1)
                    if score < best:
                        best, best_n = score, n
        return best_n if best < 0.35 else None

    def _classify(self, gray, prefix: str, region) -> Tuple[Optional[str], float]:
        best, kind = 0.0, None
        tpl_dir = os.path.join(self.image.img_dir, 'labels', 'misty')
        for fname in sorted(os.listdir(tpl_dir)):
            if fname.startswith(prefix) and fname.endswith('.png'):
                score, _ = self._score(gray, f'labels/misty/{fname[:-4]}', region)
                if score > best:
                    best, kind = score, fname[len(prefix):-4]
        return kind, best

    def read_stage(self, bgr=None, gray=None) -> Optional[StageInfo]:
        if gray is None:
            bgr, gray = self._shot()
        if not self._in_stage_window(gray):
            return None
        number = self._stage_number(gray)
        if number is None:
            return None
        stamps = {row: self._score(gray, 'labels/misty/completed_stamp', (640, y0, 300, y1 - y0))[0] >= 0.6
                  for row, (y0, y1) in STAMP_ROWS.items()}
        silver, s_score = self._classify(gray, 'silver_', (300, 830, 660, 140))
        gold, g_score = self._classify(gray, 'gold_', (300, 1050, 660, 140))
        if s_score < 0.85:
            silver = None
        if g_score < 0.85:
            gold = 'unknown'
        timer = self._score(gray, 'labels/misty/opens_timer', (330, 1420, 260, 110))[0] >= 0.8
        btn = bgr[1545:1615, 380:700].astype(int)
        playable = int(((btn[..., 0] > 200) & (btn[..., 1] > 190) & (btn[..., 2] < 170)).sum()) > 1000
        return StageInfo(number, stamps['stone'], stamps['silver'], stamps['gold'],
                         silver, gold, timer, playable)

    def _open_stage(self, x: int, y: int) -> Optional[StageInfo]:
        self.controller.tap(x + HUT_TAP_OFFSET[0], y + HUT_TAP_OFFSET[1], seconds=1.5)
        for _ in range(4):
            info = self.read_stage()
            if info:
                return info
            self.wait(0.7)
        return None

    def _close_stage(self) -> None:
        self.controller.tap(*STAGE_CLOSE, seconds=1)

    # -- formation ---------------------------------------------------------

    def _in_formation(self, gray) -> bool:
        return self._score(gray, 'labels/misty/formation_remove', (960, 1040, 120, 130))[0] >= 0.8

    def _panel_expanded(self, gray=None) -> bool:
        if gray is None:
            _, gray = self._shot()
        return self._score(gray, 'labels/misty/panel_middle_row', (200, 1500, 380, 150))[0] >= 0.8

    def _ensure_panel_expanded(self) -> bool:
        """Open the filter panel. Only ever taps the ^ button of the collapsed panel:
        the spot of the collapse button is a hero card when the panel is collapsed."""
        for _ in range(3):
            _, gray = self._shot()
            if self._panel_expanded(gray):
                return True
            score, pos = self._score(gray, 'labels/misty/panel_expand_btn', (0, 1600, 200, 200))
            if score >= 0.8:
                self.controller.tap(*pos, seconds=0.5)
            # wait for the panel to slide open
            end = time.time() + 3
            while time.time() < end:
                if self._panel_expanded():
                    return True
                time.sleep(0.3)
        return False

    def _remove_all(self) -> None:
        self.controller.tap(*REMOVE_ALL, seconds=1)
        end = time.time() + 3
        while time.time() < end:
            _, gray = self._shot()
            score, pos = self._score(gray, 'labels/misty/notice_confirm', (300, 1150, 480, 220))
            if score >= 0.8:
                self.controller.tap(*pos, seconds=1)
                return
            time.sleep(0.3)
        # No notice: the formation was already empty

    def _set_filter(self, faction: str, cls: str) -> bool:
        """Faction first, then class.

        The faction row is visible whether the panel is open or not. The class row
        is only touched when a class is needed (or a class set earlier has to be
        reset to ALL), and only once the panel is confirmed open.
        """
        if self._faction is None and faction != ALL:
            # Unknown state: go via ALL so a faction that's already selected isn't tapped off
            self.controller.tap(FACTION_X[ALL], FACTION_Y, seconds=0.6)
            self._faction = ALL
        if faction != self._faction:
            self.controller.tap(FACTION_X[faction], FACTION_Y, seconds=0.8)
            self._faction = faction
        if cls != ALL or self._class != ALL:
            if not self._ensure_panel_expanded():
                return False
            self.controller.tap(CLASS_X[cls], CLASS_Y, seconds=0.8)
            self._class = cls
        return True

    def _cards(self) -> List[Tuple[int, bool]]:
        """Top-row hero cards as (x, already placed), left to right"""
        bgr, _ = self._shot()
        cards = []
        for x in CARD_XS:
            cell = bgr[1175:1330, x - 75:x + 75].astype(int)
            if cell.mean(-1).std() < 20:      # empty slot
                break
            b, g, r = cell[..., 0], cell[..., 1], cell[..., 2]
            checked = int(((g > 190) & (g - r > 40) & (g - b > 80)).sum()) > 500
            cards.append((x, checked))
        return cards

    def _place(self, x: int) -> bool:
        """Tap a top-row card once (a second tap would take the hero out again)"""
        self.controller.tap(x, CARD_Y, seconds=0.5)
        end = time.time() + 2
        while time.time() < end:
            if any(cx == x and checked for cx, checked in self._cards()):
                return True
            time.sleep(0.3)
        return False

    def build_team(self, plan: List[Slot]) -> bool:
        """Place 5 heroes following the plan. False if a slot can't be filled."""
        self._remove_all()
        self._faction = None   # unknown after the formation reloads; tap it again
        used: List[str] = []
        for i, slot in enumerate(plan):
            if len(used) >= 5:
                break
            factions = [f for f in slot.factions if not (slot.distinct and f in used)]
            placed = False
            for faction in factions:
                for cls in slot.classes:
                    if not self._set_filter(faction, cls):
                        logger.warning("    Filter panel not found")
                        return False
                    # Strongest first: top row, left to right, skipping heroes already placed
                    free = [x for x, checked in self._cards() if not checked]
                    if free and self._place(free[0]):
                        used.append(faction)
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                logger.debug(f"    Could not fill slot {i + 1}: {slot}")
                return False
        return True

    # -- battle ------------------------------------------------------------

    def _fight(self) -> Optional[bool]:
        """Press Battle and wait for the result. True = victory, False = defeat, None = unknown"""
        self.controller.tap(*FORMATION_BATTLE, seconds=3)
        end = time.time() + 90
        while time.time() < end:
            if self._stopped():
                return None
            _, gray = self._shot()
            if self._score(gray, 'labels/misty/tap_to_close', (250, 1650, 580, 150))[0] >= 0.8:
                won = self._score(gray, 'labels/misty/victory', (150, 450, 780, 300))[0] >= 0.7
                self.controller.tap(540, 1700, seconds=3)
                return won
            time.sleep(2)
        return None

    def _run_battle(self, info: StageInfo, mem: StageMemory, plan: BattlePlan) -> None:
        logger.purple(f"    Stage {info.number}: battle for {plan.label}")
        self.controller.tap(*STAGE_BATTLE, seconds=2)
        # The game shows a cloud transition before the formation screen
        if not self._wait_for('labels/misty/formation_remove', timeout=15, region=(960, 1040, 120, 130)):
            if self._stopped():
                return
            logger.warning("    Formation screen not found")
            mem.attempts += 1
            self.controller.recover(silent=True)
            return
        self.wait(0.5)   # let the hero list finish loading
        built = any(self.build_team(p) for p in plan.plans)
        if not built:
            if plan.covers_silver:
                mem.silver_impossible = True
                logger.warning(f"    Not enough heroes for the Silver challenge on stage {info.number}")
            if plan.covers_gold:
                mem.gold_impossible = True
                logger.warning(f"    Not enough heroes for the Gold challenge on stage {info.number}")
            if plan.fallback_any:
                built = self.build_team(any_plan())
        if not built:
            self.controller.tap(*FORMATION_BACK, seconds=2)
            return
        mem.attempts += 1
        result = self._fight()
        if result is True:
            logger.green(f"    Stage {info.number}: victory")
        elif result is False:
            logger.warning(f"    Stage {info.number}: defeat")
        else:
            logger.warning(f"    Stage {info.number}: battle result not found")
            self.controller.recover(silent=True)
        # Back to the map, through the cloud transition again
        self._wait_for('labels/misty/map_title', timeout=15, region=(300, 20, 480, 100))
        self.wait(1.5)   # the camera pans after a win

    # -- main loop ---------------------------------------------------------

    def run(self, stop_event=None, pause_event=None) -> bool:
        """Clear Misty Valley up to stage 20"""
        self._stop_event, self._pause_event = stop_event, pause_event
        logger.blue("Running Misty Valley")
        if not self.enter():
            return False
        if self._stopped():
            return False

        memory: Dict[int, StageMemory] = {}
        finished = set()
        scrolls = reentries = 0
        recentred = True   # entering already centres on the cart

        for _ in range(200):
            if self._stopped():
                logger.info("Misty Valley stopped")
                return False
            if not self._on_map():
                # Possibly still in a cloud transition: give it a moment first
                if not self._wait_for('labels/misty/map_title', timeout=8, region=(300, 20, 480, 100)):
                    if self._stopped():
                        logger.info("Misty Valley stopped")
                        return False
                    if reentries >= 3 or not self.reenter():
                        if not self._stopped():
                            logger.error("    Lost the Misty Valley map, stopping")
                        return False
                    reentries += 1

            _, gray = self._shot()
            acted = False
            for x, y in self._stage_huts(gray):
                info = self._open_stage(x, y)
                if info is None:
                    continue
                n = info.number
                if n in finished:
                    self._close_stage()
                    continue
                if info.timer:
                    logger.info(f"    Stage {n} isn't open yet, Misty Valley done for now")
                    self._close_stage()
                    return True
                mem = memory.setdefault(n, StageMemory())
                plan = next_battle(info, mem)
                if plan is None:
                    logger.green(f"    Stage {n} done")
                    finished.add(n)
                    self._close_stage()
                    if n >= LAST_STAGE:
                        logger.green("Misty Valley complete (stage 20)")
                        return True
                    continue
                if not info.playable:
                    logger.warning(f"    Stage {n} is locked, stopping")
                    self._close_stage()
                    return False
                self._run_battle(info, mem, plan)
                acted = True
                break

            if acted:
                scrolls = 0
                recentred = False
                continue
            if not recentred and (scrolls >= 3 or not self._stage_huts(gray)):
                # Leaving and re-entering puts the camera back on the cart
                logger.debug("    Re-entering Misty Valley to centre on the cart")
                if self._stopped() or not self.reenter():
                    return False
                recentred = True
                scrolls = 0
                continue
            if scrolls >= 6:
                logger.warning("    No more stages found")
                return True
            self._scroll_up()
            scrolls += 1

        logger.warning("Misty Valley: step limit reached")
        return False
