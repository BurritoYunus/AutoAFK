"""Shadow Realm (Realm of Shadows) in Golden Frontier

Campaign -> Golden Frontier -> Shadow Realm shortcut -> Go, then on the tower:

* Tap every "Receive" (closes the rewards popup by tapping the top of the screen).
* Take the "Challenge" buttons one by one, top to bottom, left to right.
* For each battle pick the team with the most attempts left ("3/6"); teams that are
  "Recovering Blessed Flames" (0/6) are skipped.
* Stop when no team has attempts, when no Challenge is left (boss not beaten by the
  guild yet, locked floors), or at the "Highest explorable floor" read on entry.

Everything on the tower and the team screen is read with text recognition, so it
doesn't depend on how many nodes a floor has.
"""
import logging
import re
import time
from typing import List, Optional, Tuple

from PIL import Image

from src.activities.base_activity import BaseActivity
from src.core import ocr

logger = logging.getLogger(__name__)

# Screen positions (1080x1920)
GO_BUTTON = (540, 1460)            # "Go" on the Realm of Shadows popup
CLOSE_POPUP = (540, 40)            # tap here to close the rewards popup
TEAM_BATTLE = (540, 1828)
TOWER_DRAG = ((540, 1450), (540, 750))   # drag up = show lower floors

SETTLE = 1.5                       # seconds to let a screen finish animating before acting
MAX_BATTLES = 40                   # safety limit for one run
BATTLE_TIMEOUT = 150               # seconds to wait for a battle result


def _say(text: str, tag: Optional[str] = None, level: int = logging.INFO) -> None:
    logger.log(level, text, extra={'tag': tag} if tag else None)


def _norm(text: str) -> str:
    return re.sub(r'[^a-z0-9/:]', '', text.lower())


class ShadowRealmActivities(BaseActivity):
    """Runs the Shadow Realm floors"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stop_event = None
        self._pause_event = None
        self.highest_floor: Optional[int] = None

    # -- helpers -----------------------------------------------------------

    def _stopped(self) -> bool:
        if self._pause_event is not None:
            while self._pause_event.is_set() and not (self._stop_event and self._stop_event.is_set()):
                time.sleep(0.5)
        return bool(self._stop_event and self._stop_event.is_set())

    def _read(self) -> List[Tuple[int, int, str]]:
        """All text on screen as (x, y, normalised text)"""
        boxes = ocr.read_boxes(self.device.get_screenshot().convert('RGB')) or []
        texts = []
        for x, y, w, _, t in boxes:
            t = _norm(t)
            # Floors with 4 nodes put the Challenge buttons close together; if they are read
            # as one line, split it back into one entry per button
            n = t.count('challenge')
            if n > 1:
                texts += [(int(x - w / 2 + w * (i + 0.5) / n), y, 'challenge') for i in range(n)]
            else:
                texts.append((x, y, t))
        return texts

    @staticmethod
    def _find(texts, word: str, region=(0, 0, 1080, 1920)) -> List[Tuple[int, int]]:
        x0, y0, x1, y1 = region
        return [(x, y) for x, y, t in texts if word in t and x0 <= x <= x1 and y0 <= y <= y1]

    def _screen(self, texts) -> str:
        """Which screen is showing"""
        # Golden Frontier shows its leaderboard the first time it's opened each day
        if self._find(texts, 'leaderboard', (0, 0, 1080, 160)) or (
                self._find(texts, 'division', (0, 1750, 1080, 1920)) and self._find(texts, 'personal', (0, 1750, 1080, 1920))):
            return 'other'
        if self._find(texts, 'realmofshadows', (0, 0, 1080, 130)):
            return 'tower'
        if self._find(texts, 'taptocontinue'):
            return 'result'
        if self._find(texts, 'battle', (300, 1750, 780, 1900)) and (
                self._find(texts, 'vs', (400, 0, 680, 120)) or self._find(texts, 'alignment', (700, 1800, 1000, 1920))):
            return 'teams'
        if self._find(texts, 'realmofshadows', (0, 400, 1080, 650)):
            return 'popup'
        if self._find(texts, 'attack', (300, 1750, 780, 1900)):
            return 'gf_map'
        if self._find(texts, 'begin', (300, 1600, 800, 1730)):
            return 'campaign'
        return 'unknown'

    def _settle(self, seconds: float = SETTLE) -> None:
        """Give the game time to finish a transition or animation"""
        self.wait(seconds)

    def _wait_screen(self, wanted, timeout: float):
        """Wait until one of the wanted screens shows and has settled; returns (screen, texts)"""
        end = time.time() + timeout
        texts, screen = [], 'unknown'
        while time.time() < end:
            if self._stopped():
                break
            texts = self._read()
            screen = self._screen(texts)
            if screen in wanted:
                self._settle()
                texts = self._read()            # fresh read once the animation is done
                again = self._screen(texts)
                if again == screen:
                    return screen, texts
                screen = again
            time.sleep(1)
        return screen, texts

    def _wait_gone(self, screen: str, timeout: float) -> None:
        """Wait until a screen has closed"""
        end = time.time() + timeout
        while time.time() < end and not self._stopped():
            if self._screen(self._read()) != screen:
                self._settle()
                return
            time.sleep(1)

    # -- entering ----------------------------------------------------------

    def enter(self, from_campaign: bool = True) -> bool:
        """Campaign -> Golden Frontier -> Shadow Realm shortcut -> Go"""
        if from_campaign:
            logger.info("    Opening Shadow Realm")
            self.controller.confirm_location('campaign')
            self.controller.expand_menus()
        end = time.time() + 75
        unknown = 0
        while time.time() < end:
            if self._stopped():
                return False
            texts = self._read()
            screen = self._screen(texts)
            if screen not in ('unknown', 'tower'):
                # Let the screen finish sliding in before tapping anything on it
                self._settle()
                texts = self._read()
                if self._screen(texts) != screen:
                    continue
            if screen == 'tower':
                self._read_highest(texts)
                return True
            if screen == 'popup':
                self._read_highest(texts)
                if not self.image.click_image('labels/shadow/popup_go', confidence=0.8, seconds=3, suppress=True):
                    self.controller.tap(*GO_BUTTON, seconds=4)
            elif screen == 'gf_map':
                # The shortcut on the left moves the camera to the realm and opens it (its height
                # changes with the other event icons in that column)
                if self.image.click_image('labels/shadow/gf_realm_shortcut', confidence=0.8, seconds=3,
                                          suppress=True, region=(0, 800, 260, 900)):
                    logger.debug("    Tapped Shadow Realm shortcut")
                else:
                    enter = self._find(texts, 'enter')
                    if enter:
                        logger.debug(f"    Tapped Enter at {enter[0]}")
                        self.controller.tap(enter[0][0] + 40, enter[0][1] - 50, seconds=2)
                    else:
                        # Never Return here: that would leave Golden Frontier. Just look again.
                        time.sleep(1)
            elif screen == 'campaign':
                if self.image.click_image('labels/shadow/campaign_gf', confidence=0.8, seconds=1,
                                          suppress=True, region=(0, 600, 260, 300)):
                    logger.debug("    Tapped Golden Frontier (image)")
                else:
                    gf = self._find(texts, 'golden', (0, 600, 260, 900))
                    if not gf:
                        time.sleep(1)
                        continue
                    logger.debug(f"    Tapped Golden Frontier (text at {gf[0]})")
                    self.controller.tap(gf[0][0], gf[0][1], seconds=1)
                # Wait for Golden Frontier to open: tapping the same spot again on its map
                # would hit one of the map's own buttons
                self._wait_gone('campaign', 15)
            elif screen == 'other':
                # The daily Golden Frontier leaderboard (or another screen): Return
                # One Return goes back to the map; wait for it to close so it isn't tapped twice
                # (a second Return would leave Golden Frontier)
                logger.debug("    Leaderboard showing, tapping Return")
                self.controller.tap(55, 1830, seconds=1)
                self._wait_gone('other', 10)
            else:
                unknown += 1
                if unknown % 8 == 0:
                    self.controller.tap(55, 1830, seconds=2)   # stuck on an unknown screen: back
                time.sleep(1)
        if not self._stopped():
            logger.error("    Shadow Realm not found")
        return False

    def reenter(self) -> bool:
        """Back once to the Golden Frontier map and in again (re-centres the tower)"""
        self.controller.tap(55, 1830, seconds=3)
        if self.enter(from_campaign=False):
            return True
        if self._stopped():
            return False
        self.controller.recover(silent=True)
        return self.enter()

    def _read_highest(self, texts) -> None:
        if self.highest_floor is not None:
            return
        for _, _, t in texts:
            if 'highestexplorablefloor' in t:
                m = re.search(r'floor:?(\d+)', t)
                if m:
                    self.highest_floor = int(m.group(1))
                    _say(f"    Highest explorable floor: {self.highest_floor}", 'dim')
                    return

    # -- tower -------------------------------------------------------------

    @staticmethod
    def _floor_labels(texts) -> List[Tuple[int, int]]:
        """(y, floor number) of the 'Floor N' labels on screen"""
        out = []
        for _, y, t in texts:
            m = re.fullmatch(r'floor(\d+)', t)
            if m and 200 < y < 1700:
                out.append((y, int(m.group(1))))
        return sorted(out)

    def _challenges(self, texts) -> List[Tuple[int, int, Optional[int]]]:
        """Challenge buttons as (x, y, floor), top to bottom, left to right"""
        floors = self._floor_labels(texts)
        out = []
        # skip "Limited-Time Challenge" at the top right and the reward bar at the bottom
        for x, y in self._find(texts, 'challenge', (0, 250, 1080, 1700)):
            above = [n for fy, n in floors if fy < y]
            out.append((x, y, above[-1] if above else None))
        return sorted(out, key=lambda c: (c[1] // 40, c[0]))

    def _collect_rewards(self, texts) -> int:
        """Tap every Receive. The rewards popup only appears once all nodes of a
        floor are received, so it's closed after the last Receive of each floor."""
        receives = sorted(self._find(texts, 'receive', (0, 250, 1080, 1700)), key=lambda r: (r[1] // 40, r[0]))
        # group the buttons by floor (same row)
        rows: List[List[Tuple[int, int]]] = []
        for x, y in receives:
            if rows and abs(rows[-1][0][1] - y) < 40:
                rows[-1].append((x, y))
            else:
                rows.append([(x, y)])
        for row in rows:
            for x, y in row:
                self.controller.tap(x, y, seconds=1.5)
            self._settle()
            self.controller.tap(*CLOSE_POPUP, seconds=1.5)   # close the floor's rewards popup
        if receives:
            _say(f"    🎁 Collected {len(receives)} reward{'s' if len(receives) > 1 else ''}", 'green')
        return len(receives)

    def _scroll_down(self) -> bool:
        """Show lower floors. False if the tower didn't move (bottom reached)."""
        before = self.device.get_screenshot().convert('L')
        (x1, y1), (x2, y2) = TOWER_DRAG
        self.controller.swipe(x1, y1, x2, y2, duration=800, seconds=1.5)
        after = self.device.get_screenshot().convert('L')
        diff = sum(abs(a - b) for a, b in zip(before.resize((54, 96)).getdata(), after.resize((54, 96)).getdata()))
        return diff / (54 * 96) > 4

    # -- teams -------------------------------------------------------------

    def _teams(self, texts) -> List[Tuple[int, int, int]]:
        """Teams on the setup screen as (attempts, max, y of the row)"""
        teams = []
        for x, y, t in texts:
            m = re.fullmatch(r'(\d)/(\d)', t)
            if m and x < 220 and 1100 < y < 1750:
                teams.append((int(m.group(1)), int(m.group(2)), y - 55))
        return teams

    def _pick_team(self) -> Optional[int]:
        """Select the team with the most attempts left on the list. Returns its attempts, or None.

        Looks at the visible teams first; scrolls down for more teams only if none
        of the visible ones has attempts.
        """
        for _ in range(4):
            texts = self._read()
            teams = self._teams(texts)
            ready = [t for t in teams if t[0] > 0]
            if ready:
                attempts, _, row_y = max(ready, key=lambda t: t[0])
                self.controller.tap(600, row_y, seconds=1.5)   # tapping the row selects the team
                return attempts
            if self._find(texts, 'afterqueueexpansion') or not teams:
                return None   # end of the list (locked slot showing)
            self.controller.swipe(540, 1600, 540, 1250, duration=600, seconds=1)
        return None

    # -- battle ------------------------------------------------------------

    def _battle(self, x: int, y: int, floor: Optional[int]) -> str:
        """Fight one node. Returns 'won', 'no_attempts' or 'failed'."""
        self.controller.tap(x, y, seconds=2)
        screen, texts = self._wait_screen({'teams'}, timeout=25)
        if screen != 'teams':
            return 'failed'
        attempts = self._pick_team()
        if attempts is None:
            self.controller.tap(55, 1830, seconds=2)   # back to the tower
            return 'no_attempts'
        where = f"Floor {floor}" if floor else "next node"
        _say(f"    ⚔ Battle: {where} (team with {attempts}/6 attempts)", 'purple')
        self.controller.tap(*TEAM_BATTLE, seconds=3)
        # If the battle didn't start (still on the team screen), give up on this node
        screen, texts = self._wait_screen({'result', 'tower', 'unknown'}, timeout=12)
        if screen == 'teams':
            logger.warning("    Battle didn't start")
            self.controller.tap(55, 1830, seconds=2)
            return 'failed'
        if screen not in ('result', 'tower'):
            screen, texts = self._wait_screen({'result', 'tower'}, timeout=BATTLE_TIMEOUT)
        if screen == 'result':
            # Shadow Realm battles can't be lost
            self.controller.tap(540, 1800, seconds=2)
            self._wait_screen({'tower'}, timeout=20)
            _say("    ✔ Victory", 'green')
            return 'won'
        if screen == 'tower':
            # Back on the tower without a result screen: the battle is done
            _say("    ✔ Victory", 'green')
            return 'won'
        return 'failed'

    def _boss_tracker(self, texts) -> Optional[str]:
        """Guild progress on a boss floor (every 20 floors), e.g. "16/40", if it's showing"""
        for x, y, t in texts:
            if x > 600 and 250 < y < 1700 and re.fullmatch(r'\d+/\d+', t):
                return t
        if self._find(texts, 'defeated', (0, 250, 1080, 1700)):
            return '?'
        return None

    # -- main --------------------------------------------------------------

    def run(self, stop_event=None, pause_event=None) -> bool:
        self._stop_event, self._pause_event = stop_event, pause_event
        self.highest_floor = None
        logger.blue("Running Shadow Realm")
        if not ocr.available():
            logger.error("    Shadow Realm needs text recognition (rapidocr), which isn't available")
            return False
        result = False
        battles = 0
        try:
            result, battles = self._run()
        finally:
            if not self._stopped():
                _say("━━ Shadow Realm summary " + '━' * 17, 'blue')
                _say(f"    {battles} battle{'s' if battles != 1 else ''} this run", 'green')
                self.controller.recover(silent=True)   # back to the campaign screen
        return result

    def _run(self) -> Tuple[bool, int]:
        battles = 0
        if not self.enter():
            return False, battles
        reentries = 0
        scrolled_empty = 0
        confirmed = False
        while battles < MAX_BATTLES:
            if self._stopped():
                logger.info("Shadow Realm stopped")
                return False, battles
            screen, texts = self._wait_screen({'tower'}, timeout=10)
            if screen != 'tower':
                if reentries >= 3 or not self.reenter():
                    logger.error("    Lost the Shadow Realm screen, stopping")
                    return False, battles
                reentries += 1
                continue
            if self._collect_rewards(texts):
                texts = self._read()
            challenges = self._challenges(texts)
            if self.highest_floor is not None:
                challenges = [c for c in challenges if c[2] is None or c[2] <= self.highest_floor]
                floors = [n for _, n in self._floor_labels(texts)]
                if not challenges and floors and min(floors) > self.highest_floor:
                    _say(f"✔ Reached the highest explorable floor ({self.highest_floor})", 'green')
                    return True, battles
            if not challenges:
                # A boss floor with the guild tracker and no Challenge: the boss is done and the
                # next floors open once enough of the guild has beaten it
                tracker = self._boss_tracker(texts)
                if tracker:
                    progress = f" ({tracker} guild members)" if tracker != '?' else ''
                    _say(f"✔ Boss done, waiting for the guild to catch up{progress}", 'green')
                    return True, battles
                if scrolled_empty < 2 and self._scroll_down():
                    scrolled_empty += 1
                    continue
                if not confirmed:
                    # Back to the map and in again, so the tower shows the current floor
                    confirmed = True
                    scrolled_empty = 0
                    logger.debug("    No Challenge visible, re-entering to check")
                    if self.reenter():
                        continue
                    return False, battles
                _say("✔ Nothing left to challenge right now", 'green')
                return True, battles
            scrolled_empty = 0
            confirmed = False
            x, y, floor = challenges[0]
            outcome = self._battle(x, y, floor)
            if outcome == 'no_attempts':
                _say("✔ No attempts left on any team", 'green')
                return True, battles
            if outcome == 'won':
                battles += 1
            else:
                logger.warning("    Couldn't start the battle, re-entering")
                if reentries >= 3 or not self.reenter():
                    return False, battles
                reentries += 1
        logger.warning("Shadow Realm: battle limit reached")
        return True, battles
