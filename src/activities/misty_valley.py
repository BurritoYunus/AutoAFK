"""Misty Valley event

Clears the Misty Valley stages from wherever the map opens, up to the top of the map.

For every stage it reads the challenges from the stage window with text
recognition, so new challenges each month are understood without code changes,
and builds a team with the in-game faction and class filters, always taking the
strongest heroes (top-left first):

* "Win with N <faction(s)> heroes", "N different factions", "Frontline/Backline
  must be <class>", "same class" and "without any <class>" are turned into team
  rules. Rules from the Silver and Gold challenges are combined into one team when
  possible, otherwise they get separate battles.
* Anything else (time limits, no deaths, ultimates) only needs a win.
* "Victorious Team Contains" (specific heroes) is skipped.

The run stops at the top of the map, or at a stage that shows an "Opens:" timer.
"""
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.activities.base_activity import BaseActivity
from src.core import ocr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Game data and screen layout (1080x1920)
# ---------------------------------------------------------------------------

FACTIONS = ['lightbearer', 'mauler', 'wilder', 'graveborn',
            'celestial', 'hypogean', 'dimensional', 'draconis']
CLASSES = ['warrior', 'tank', 'ranger', 'mage', 'support']
ALL = 'all'

MAX_ATTEMPTS_PER_STAGE = 4
MAX_DEFEATS_PER_STAGE = 2

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
MAP_BACK = (55, 1815)


# ---------------------------------------------------------------------------
# Reading challenges (pure logic, no screen access)
# ---------------------------------------------------------------------------

FACTION_NAMES = {'lightbearer': 'Lightbearer', 'mauler': 'Mauler', 'wilder': 'Wilder',
                 'graveborn': 'Graveborn', 'celestial': 'Celestial', 'hypogean': 'Hypogean',
                 'dimensional': 'Dimensional', 'draconis': 'Draconis'}
# OCR sometimes cuts words short (e.g. under a COMPLETED stamp), so match on prefixes
FACTION_KEYS = {'lightb': 'lightbearer', 'mauler': 'mauler', 'wilder': 'wilder', 'graveb': 'graveborn',
                'celest': 'celestial', 'hypoge': 'hypogean', 'dimens': 'dimensional', 'dracon': 'draconis'}


def _norm(text: str) -> str:
    return re.sub(r'[^a-z0-9/]', '', text.lower())


def _classes_in(t: str) -> List[str]:
    return [c for c in CLASSES if c in t]


def _factions_in(t: str) -> List[str]:
    found = []
    for key, faction in FACTION_KEYS.items():
        i = t.find(key)
        if i >= 0:
            found.append((i, faction))
    return [f for _, f in sorted(found)]


@dataclass(frozen=True)
class Requirement:
    """What one challenge asks of the team"""
    text: str = ''
    groups: Tuple[Tuple[Tuple[str, ...], int], ...] = ()   # (factions, how many heroes)
    distinct: int = 0                                       # N different factions
    front: Optional[frozenset] = None                       # classes allowed in the frontline
    back: Optional[frozenset] = None                        # classes allowed in the backline
    exclude: frozenset = frozenset()                        # classes not allowed
    same_class: bool = False
    skip: bool = False                                      # can't be automated (specific heroes)

    @property
    def shaped(self) -> bool:
        """True if the team has to be built a particular way"""
        return bool(self.groups or self.distinct or self.front or self.back
                    or self.exclude or self.same_class)

    def describe(self) -> str:
        if self.skip:
            return 'specific heroes (skipped)'
        parts = []
        for factions, n in self.groups:
            parts.append(f"{n} {'/'.join(FACTION_NAMES[f] for f in factions)}")
        if self.distinct:
            parts.append(f'{self.distinct} different factions')
        if self.front:
            parts.append('Frontline ' + '/'.join(c.title() for c in CLASSES if c in self.front))
        if self.back:
            parts.append('Backline ' + '/'.join(c.title() for c in CLASSES if c in self.back))
        if self.exclude:
            parts.append('no ' + '/'.join(c.title() for c in CLASSES if c in self.exclude))
        if self.same_class:
            parts.append('all the same class')
        if parts:
            return ', '.join(parts)
        return ' '.join(self.text.split()) or 'win the battle'


def parse_challenge(text: Optional[str]) -> Optional[Requirement]:
    """Turn a challenge text into a Requirement. None if there's no text."""
    if not text or not text.strip():
        return None
    t = _norm(text)
    if 'victorious' in t or 'contains' in t:
        return Requirement(text=text, skip=True)
    groups, distinct, front, back, exclude, same = [], 0, None, None, frozenset(), False
    m = re.search(r'(\d)differentfaction', t)
    if m or 'differentfaction' in t:
        distinct = int(m.group(1)) if m else 5
    else:
        m = re.search(r'with(\d)(.*?)hero', t)
        if m:
            factions = _factions_in(m.group(2))
            if factions:
                groups.append((tuple(factions), int(m.group(1))))
    if 'frontline' in t:
        cls = _classes_in(t[t.index('frontline'):])
        front = frozenset(cls) if cls else None
    if 'backline' in t:
        cls = _classes_in(t[t.index('backline'):])
        back = frozenset(cls) if cls else None
    if 'without' in t:
        exclude = frozenset(_classes_in(t[t.index('without'):]))
    if 'sameclass' in t:
        same = True
    return Requirement(text=text, groups=tuple(groups), distinct=distinct, front=front,
                       back=back, exclude=exclude, same_class=same)


# ---------------------------------------------------------------------------
# Team planning (pure logic, no screen access)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """One hero to place: try factions in order, and classes in order for each"""
    factions: Tuple[str, ...]
    classes: Tuple[str, ...] = (ALL,)
    distinct: bool = False   # pick a faction not used yet in this team


def any_plan() -> List[Slot]:
    """The 5 strongest heroes"""
    return [Slot((ALL,))] * 5


def build_plans(reqs: List[Requirement]) -> List[List[Slot]]:
    """Team plans that meet all the requirements at once (empty if they can't be combined).

    Heroes are placed in order: the first 2 are the frontline, the last 3 the backline.
    """
    groups = [g for r in reqs for g in r.groups]
    distinct = max((r.distinct for r in reqs), default=0)
    if distinct and groups:
        return []          # "N of one faction" and "N different factions" don't mix
    if sum(n for _, n in groups) > 5:
        return []
    every = set(CLASSES)
    allowed = [set(every) for _ in range(5)]
    for r in reqs:
        for i in range(5):
            allowed[i] -= r.exclude
        if r.front:
            for i in (0, 1):
                allowed[i] &= r.front
        if r.back:
            for i in (2, 3, 4):
                allowed[i] &= r.back
    variants = [allowed]
    if any(r.same_class for r in reqs):
        variants = [[a & {c} for a in allowed] for c in CLASSES]

    plans: List[List[Slot]] = []
    for al in variants:
        if any(not a for a in al):
            continue
        cls = []
        for i, a in enumerate(al):
            if a != every:
                cls.append(tuple(c for c in CLASSES if c in a))
                continue
            # Free position: if later positions need certain classes, use other classes
            # first so those heroes are still available when their turn comes
            later = set().union(*[b for b in al[i + 1:] if b != every]) if i < 4 else set()
            if later and later != every:
                cls.append(tuple([c for c in CLASSES if c not in later] + [c for c in CLASSES if c in later]))
            else:
                cls.append((ALL,))
        orders = [list(range(5))]
        if groups:
            orders.append(list(range(4, -1, -1)))   # also try the group in the backline
        for order in orders:
            fac: List[Optional[Tuple[str, ...]]] = [None] * 5
            k = 0
            for factions, n in groups:
                for _ in range(n):
                    fac[order[k]] = factions
                    k += 1
            plan = []
            for i in range(5):
                if distinct:
                    plan.append(Slot(tuple(FACTIONS), cls[i], distinct=True))
                else:
                    plan.append(Slot(fac[i] or (ALL,), cls[i]))
            if plan not in plans:
                plans.append(plan)
    return plans


@dataclass
class StageInfo:
    number: int
    stone_done: bool
    silver_done: bool
    gold_done: bool
    silver: Optional[Requirement]
    gold: Optional[Requirement]
    timer: bool
    playable: bool


@dataclass
class StageMemory:
    attempts: int = 0
    defeats: int = 0
    silver_impossible: bool = False
    gold_impossible: bool = False
    logged: bool = False


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
    s, g = info.silver, info.gold
    silver_needed = bool(not info.silver_done and s and not s.skip and not mem.silver_impossible)
    gold_needed = bool(not info.gold_done and g and not g.skip and not mem.gold_impossible)
    s_shape, g_shape = silver_needed and s.shaped, gold_needed and g.shaped
    s_win, g_win = silver_needed and not s.shaped, gold_needed and not g.shaped
    stone_needed = not info.stone_done

    if not (s_shape or g_shape or s_win or g_win or stone_needed):
        return None
    if mem.attempts >= MAX_ATTEMPTS_PER_STAGE or mem.defeats >= MAX_DEFEATS_PER_STAGE:
        return None

    if s_shape and g_shape:
        plans = build_plans([s, g]) + build_plans([s])
        return BattlePlan(f'{s.describe()} + {g.describe()}', plans, covers_silver=True,
                          fallback_any=stone_needed)
    if s_shape:
        return BattlePlan(s.describe(), build_plans([s]), covers_silver=True, fallback_any=stone_needed)
    if g_shape:
        return BattlePlan(g.describe(), build_plans([g]), covers_gold=True, fallback_any=stone_needed)
    # Only a plain win is left: the 5 strongest heroes
    wins = [r.describe() for r, need in ((s, s_win), (g, g_win)) if need]
    return BattlePlan(' + '.join(wins) or 'win the battle', [any_plan()])


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

    def enter(self, from_campaign: bool = True) -> bool:
        """Campaign -> Events -> Adventure -> Misty Valley -> world map flag -> Continue Adventure.

        Works out which of those screens is showing and does the next step, so it
        copes with the game remembering the Adventure tab or skipping a screen.
        """
        if from_campaign:
            logger.info("    Opening Misty Valley")
            self.controller.confirm_location('campaign')
            self.controller.expand_menus()
        end = time.time() + (60 if from_campaign else 20)
        idle = 0
        while time.time() < end:
            if self._stopped():
                return False
            _, gray = self._shot()
            if self._score(gray, 'labels/misty/map_title', (300, 20, 480, 100))[0] >= 0.8:
                self.wait(2)   # let the camera settle on the cart
                return True
            # "Continue Adventure" popup
            score, pos = self._score(gray, 'labels/misty/entry_continue', (300, 1400, 480, 260))
            if score >= 0.8:
                self.controller.tap(*pos, seconds=2)
                continue
            # World map: the flag is just above the "Misty Valley" label
            score, pos = self._score(gray, 'labels/misty/entry_world_icon', (0, 450, 1080, 1300))
            if score >= 0.8:
                self.controller.tap(pos[0], pos[1] - 140, seconds=2)
                continue
            # Events screen: open the Adventure tab, then the Misty Valley banner
            if self._score(gray, 'labels/misty/entry_events_header', (250, 0, 580, 140))[0] >= 0.8:
                score, pos = self._score(gray, 'labels/misty/entry_event_banner', (0, 240, 1080, 1450))
                if score >= 0.8:
                    self.controller.tap(*pos, seconds=3)
                else:
                    self.controller.tap(490, 1835, seconds=2)
                continue
            # Campaign screen: Events button
            if self.image.click_image('buttons/events', confidence=0.8, seconds=3, suppress=True,
                                      region=(0, 150, 300, 1100)):
                continue
            # Loading or a transition: wait, then try to get back to campaign
            idle += 1
            if idle in ((8, 16) if from_campaign else (16,)):
                self.controller.recover(silent=True)
            time.sleep(0.5)
        if not self._stopped():
            logger.error("    Misty Valley map not found")
        return False

    def reenter(self) -> bool:
        """Back once to the world map and in again (re-centres the camera on the cart)"""
        logger.debug("    Re-entering Misty Valley")
        self.controller.tap(*MAP_BACK, seconds=2)
        if self.enter(from_campaign=False):
            return True
        if self._stopped():
            return False
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

    def _scroll_up(self) -> bool:
        """Show the stages further up by dragging the map down.

        (Tapping a gate doesn't move the camera.) Returns False if the map
        didn't move, i.e. the top of the map is reached.
        """
        _, before = self._shot()
        # The path wanders left and right, and after a win the camera pans to the
        # rewards. Pull the map sideways too, so the highest gate or stage on screen
        # (the way up) comes back to the middle.
        anchors = [(y, x) for x, y in self._stage_huts(before)] + \
                  [(y, x) for x, y, _ in self._gates(before)]
        dx = 0
        if anchors:
            _, top_x = min(anchors)
            dx = max(-400, min(400, 540 - top_x))
        # Slow drag starting away from stages and buttons, so it doesn't fling
        start_x = 300 if dx >= 0 else 780
        self.controller.swipe(start_x, 650, start_x + dx, 1350, duration=900, seconds=1.5)
        _, after = self._shot()
        region = (slice(250, 1650), slice(0, 1080))
        moved = float(np.abs(before[region].astype(int) - after[region].astype(int)).mean()) > 4
        if not moved:
            logger.debug("    Map didn't move: top reached")
        return moved

    # -- stage window ------------------------------------------------------

    def _in_stage_window(self, gray) -> bool:
        return self._score(gray, 'labels/misty/completion_req', (280, 450, 520, 100))[0] >= 0.8

    def _stage_number(self, gray) -> Optional[int]:
        """Stage number from the window title (binarised text comparison)"""
        mask = gray > 200
        best, best_n = 1.0, None
        for n in range(1, 21):
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

    # Text the image templates stand for, used when OCR isn't available
    TEMPLATE_TEXT = {
        'silver_lightbearer': 'Win with 4 Lightbearers heroes in your formation.',
        'silver_mauler': 'Win with 4 Maulers heroes in your formation.',
        'silver_wilder': 'Win with 4 Wilders heroes in your formation.',
        'silver_graveborn': 'Win with 4 Graveborn heroes in your formation.',
        'silver_chd': 'Win with 4 Celestial/Hypogean/Dimensional heroes in your formation.',
        'gold_factions5': 'Win with 5 different Factions in your formation.',
        'gold_frontline_tank': 'All heroes placed on the Frontline must be Tank heroes.',
        'gold_backline_ranger': 'All heroes placed on the Backline must be Ranger heroes.',
        'gold_same_class': 'All heroes in formation must be the same class.',
        'gold_no_ranger_mage': 'Win without any Ranger and Mage heroes in your formation.',
        'gold_no_tank_mage': 'Win without any Tank and Mage heroes in your formation.',
        'gold_ultimate': "Don't trigger Ultimate skills.",
        'gold_defeat_within': 'Defeat an enemy hero in time.',
        'gold_no_dying': 'Win without any heroes dying.',
        'gold_win_within': 'Win within the time limit.',
        'gold_victorious': 'Victorious Team Contains:',
    }

    def _read_stage_number(self, bgr, gray) -> Optional[int]:
        from PIL import Image
        text = ocr.read_line(Image.fromarray(cv2.cvtColor(bgr[355:410, 420:660], cv2.COLOR_BGR2RGB)))
        if text:
            m = re.search(r'(\d+)', text.replace('O', '0').replace('o', '0'))
            if m:
                return int(m.group(1))
        return self._stage_number(gray)

    def _read_challenges(self, bgr, gray) -> Tuple[Optional[str], Optional[str]]:
        """Silver and Gold challenge text, read from the screen"""
        from PIL import Image
        lines = ocr.read_lines(Image.fromarray(cv2.cvtColor(bgr[820:1190, 300:960], cv2.COLOR_BGR2RGB)))
        if lines is not None:
            silver = ' '.join(t for y, t in lines if y < 150)
            gold = ' '.join(t for y, t in lines if y > 210)
            if silver or gold:
                return silver, gold
        # Fallback: the image templates of this month's challenges
        silver, s_score = self._classify(gray, 'silver_', (300, 830, 660, 140))
        gold, g_score = self._classify(gray, 'gold_', (300, 1050, 660, 140))
        silver_text = self.TEMPLATE_TEXT.get(f'silver_{silver}') if s_score >= 0.85 else None
        gold_text = self.TEMPLATE_TEXT.get(f'gold_{gold}', 'Win.') if g_score >= 0.85 else 'Win.'
        return silver_text, gold_text

    def read_stage(self, bgr=None, gray=None) -> Optional[StageInfo]:
        if gray is None:
            bgr, gray = self._shot()
        if not self._in_stage_window(gray):
            return None
        number = self._read_stage_number(bgr, gray)
        if number is None:
            return None
        stamps = {row: self._score(gray, 'labels/misty/completed_stamp', (640, y0, 300, y1 - y0))[0] >= 0.6
                  for row, (y0, y1) in STAMP_ROWS.items()}
        silver_text, gold_text = self._read_challenges(bgr, gray)
        silver, gold = parse_challenge(silver_text), parse_challenge(gold_text)
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
        # The game keeps the class until another faction or class is picked
        if self._faction is None and faction != ALL:
            # Unknown state: go via ALL so a faction that's already selected isn't tapped off
            self.controller.tap(FACTION_X[ALL], FACTION_Y, seconds=0.6)
            self._faction, self._class = ALL, ALL
        if faction != self._faction:
            self.controller.tap(FACTION_X[faction], FACTION_Y, seconds=0.8)
            self._faction, self._class = faction, ALL
        if cls != self._class:
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
            mem.defeats += 1
            logger.warning(f"    Stage {info.number}: defeat")
            # That team was too weak: drop the challenge it was built for, so the
            # next battle uses the 5 strongest heroes and at least wins the stage
            if plan.covers_silver and not mem.silver_impossible:
                mem.silver_impossible = True
                logger.warning(f"    Giving up the Silver challenge on stage {info.number}")
            if plan.covers_gold and not mem.gold_impossible:
                mem.gold_impossible = True
                logger.warning(f"    Giving up the Gold challenge on stage {info.number}")
        else:
            logger.warning(f"    Stage {info.number}: battle result not found")
            self.controller.recover(silent=True)
        # Back to the map, through the cloud transition again
        self._wait_for('labels/misty/map_title', timeout=15, region=(300, 20, 480, 100))
        self.wait(1.5)   # the camera pans after a win

    # -- main loop ---------------------------------------------------------

    def _log_stage(self, info: StageInfo) -> None:
        def show(req, done):
            if done:
                return 'done'
            return req.describe() if req else 'not read'
        logger.info(f"    Stage {info.number}: {show(info.silver, info.silver_done)} | "
                    f"{show(info.gold, info.gold_done)}")

    def _nudge_for_stage(self) -> bool:
        """Drag the map a little in each direction until a stage shows up"""
        for dx, dy in ((300, 0), (-600, 0), (300, 300), (0, -600)):
            if self._stopped():
                return False
            self.controller.swipe(540, 1000, 540 + dx, 1000 + dy, duration=600, seconds=1)
            _, gray = self._shot()
            if self._stage_huts(gray):
                return True
        self.controller.swipe(540, 1000, 540, 1300, duration=600, seconds=1)   # back to where it was
        return False

    def run(self, stop_event=None, pause_event=None) -> bool:
        """Clear Misty Valley up to the last stage"""
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
                if not mem.logged:
                    mem.logged = True
                    self._log_stage(info)
                plan = next_battle(info, mem)
                if plan is None:
                    if not info.stone_done:
                        logger.error(f"    Couldn't win stage {n}, stopping")
                        self._close_stage()
                        return False
                    logger.green(f"    Stage {n} done")
                    finished.add(n)
                    self._close_stage()
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
            if not self._stage_huts(gray):
                # After a win the camera pans to the rewards: look around a little first
                if self._nudge_for_stage():
                    continue
                if not recentred:
                    # Leaving and re-entering puts the camera back on the cart
                    if self._stopped() or not self.reenter():
                        return False
                    recentred = True
                    scrolls = 0
                    continue
            if scrolls >= 6 or not self._scroll_up():
                logger.green("Reached the top of the map, Misty Valley done")
                return True
            scrolls += 1

        logger.warning("Misty Valley: step limit reached")
        return False
