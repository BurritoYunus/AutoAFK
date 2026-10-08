"""Shop and merchant activities"""
import logging
from src.activities.base_activity import BaseActivity

logger = logging.getLogger(__name__)


class ShopActivities(BaseActivity):
    """Handles shop purchases and merchant"""
    
    def shop_purchases(self, shop_refreshes: int, skip_quick: int = 0) -> bool:
        """Handle shop purchases with refreshes"""
        if self.config.getboolean('SHOP', 'quick', fallback=False) and skip_quick == 0:
            return self._shop_purchases_quick(shop_refreshes)
            
        logger.info(f"Attempting store purchases (Refreshes: {shop_refreshes})")
        counter = 0
        
        self.controller.confirm_location('ranhorn', 
                                        region=self.controller.BOUNDARIES['ranhornSelect'])
        self.wait(2)
        self.controller.tap(440, 1750)
        
        # Wait for store screen (max 5s)
        if self.image.wait_for_image('labels/store', timeout=5, check_interval=0.3):
            # First purchases
            self._handle_shop_purchasing(counter)
            
            # Refresh purchases
            while counter < shop_refreshes:
                self.controller.tap(1000, 300)
                self.image.click_image('buttons/confirm', suppress=True, seconds=5)
                counter += 1
                logger.green(f"Refreshed store {counter} times")
                self._handle_shop_purchasing(counter)
                
            self.image.click_image('buttons/back')
            logger.green("Store purchases attempted")
            self.wait(2)  # Wait before next task as loading ranhorn can be slow
            return True
        else:
            logger.error("Store not found")
            self.controller.recover()
            return False
            
    def _shop_purchases_quick(self, shop_refreshes: int) -> bool:
        """Quick buy shop items"""
        logger.info(f"Attempting store quickbuys (Refreshes: {shop_refreshes})")
        counter = 0
        
        self.controller.confirm_location('ranhorn')
        self.wait(2)
        self.controller.tap(440, 1750, seconds=5)  # Wait for store to load
        
        # Check for store screen with more retries
        if self.image.is_visible('labels/store', retry=3):
            if self.image.is_visible('buttons/quickbuy', click=True):
                self.wait(1)
                self.image.click_image('buttons/purchase', seconds=5)
                self.controller.tap(970, 90, seconds=2)
                
                while counter < shop_refreshes:
                    self.controller.tap(1000, 300)
                    self.image.click_image('buttons/confirm', suppress=True, seconds=4)
                    self.image.click_image('buttons/quickbuy', seconds=2)
                    self.image.click_image('buttons/purchase', seconds=2)
                    self.controller.tap(970, 90)
                    counter += 1
                    
                self.image.click_image('buttons/back')
                logger.green("Store purchases attempted")
                return True
            else:
                logger.info("Quickbuy not found, switching to old style")
                self.image.click_image('buttons/back')
                return self.shop_purchases(shop_refreshes, 1)
        else:
            logger.error("Store not found")
            self.controller.recover()
            return False

    def _handle_shop_purchasing(self, counter: int):
        """Purchase items from shop based on config

        Args:
            counter: Current refresh counter (affects purchase limits)
        """
        # Re-read config for updated values
        self.config.read(self.config.get('DEFAULT', 'settings_file', fallback='settings.ini'))

        # Top row items with coordinates
        top_row = {
            'arcanestaffs': [180, 920],
            'cores': [425, 920],
            'timegazer': [650, 920],
            'baits': [875, 920]
        }

        # Bottom row items with image buttons
        bottom_row = {
            'dust_gold': 'buttons/shop/dust',
            'shards_gold': 'buttons/shop/shards_gold',
            'dust_diamond': 'buttons/shop/dust_diamonds',
            'elite_soulstone': 'buttons/shop/soulstone',
            'superb_soulstone': 'buttons/shop/superstone',
            'silver_emblem': 'buttons/shop/silver_emblems',
            'gold_emblem': 'buttons/shop/gold_emblems',
            'poe': 'buttons/shop/poe'
        }

        # Name translations for console output
        name_map = {
            'dust_gold': 'Dust (Gold)',
            'shards_gold': 'Shards',
            'dust_diamond': 'Dust (Diamonds)',
            'elite_soulstone': 'Elite Soulstone',
            'superb_soulstone': 'Superb Soulstone',
            'silver_emblem': 'Silver Emblems',
            'gold_emblem': 'Gold Emblems',
            'poe': 'Poe Coins (Gold)',
            'arcanestaffs': 'Arcane Staffs',
            'cores': 'Elemental Cores',
            'timegazer': 'Timegazer Card',
            'baits': 'Bait'
        }

        # Purchase top row items
        for item, pos in top_row.items():
            if self.config.getboolean('SHOP', item, fallback=False):
                # Purchase limits based on refresh counter
                if item == 'timegazer' and counter > 0:  # Only one TG card
                    continue
                if item == 'baits' and counter > 1:  # Only two baits
                    continue
                if (item == 'cores' or item == 'arcanestaffs') and counter > 2:  # Only three
                    continue

                logger.purple(f"    Buying: {name_map.get(item, item)}")
                self.controller.tap(pos[0], pos[1])
                self.image.click_image('buttons/shop/purchase', suppress=True)
                self.controller.tap(550, 1220, seconds=2)

        # Scroll down to see bottom rows
        self.controller.swipe(550, 1500, 550, 1200, 500, seconds=5)

        # Purchase bottom row items
        for item, button in bottom_row.items():
            if self.config.getboolean('SHOP', item, fallback=False):
                if self.image.is_visible(button, confidence=0.95, click=True):
                    logger.purple(f"    Buying: {name_map.get(item, item)}")
                    self.image.click_image('buttons/shop/purchase', suppress=True)
                    self.controller.tap(550, 1220)

        self.wait(3)  # Long wait else Twisted Realm isn't found after if enabled

    def clear_merchant(self) -> bool:
        """Collect free merchant deals and pass rewards.

        Uses the redesigned store (Visiting Merchants / Monthly / Growth / Basic
        Emporium) when it is detected, otherwise the old merchant flow.
        """
        logger.blue("Attempting to collect merchant deals")

        self.controller.tap(120, 300, seconds=5)

        if self._is_new_store(retry=3):
            result = self._clear_merchant_emporium()
        else:
            logger.info("    New store layout not found, using old merchant flow")
            result = self._clear_merchant_legacy()

        logger.green("Merchant deals collected")
        self.controller.recover(silent=True)
        return result

    # ------------------------------------------------------------------
    # Redesigned store (Oct 2026)
    # ------------------------------------------------------------------

    # Bottom bar: label positions to tap
    EMPORIUMS = {
        'Visiting Merchants': (277, 1863),
        'Monthly Emporium': (505, 1863),
        'Growth Emporium': (730, 1863),
        'Basic Emporium': (955, 1863),
    }
    # The red ! badge of a bottom-bar entry sits about 95px right of its label centre
    EMPORIUM_BADGE_DX = 95
    BOTTOM_BADGE_REGION = (0, 1820, 1080, 70)
    # Tab bar above the bottom bar: badges sit on the top-right corner of each tab
    TAB_BADGE_REGION = (0, 1490, 1080, 60)
    TAB_FROM_BADGE = (-58, 130)  # badge centre -> tab centre
    # Content area between the top bar and the tab bar
    CONTENT_REGION = (0, 120, 1080, 1390)
    # Spot that closes reward popups without hitting anything on the pages
    DISMISS = (540, 140)
    # Pass tabs (Champions of Esperia, Twisted Bounties, Regal Rewards)
    PASS_COMMON_X = 220
    PASS_MARKER_X = 437
    PASS_ROW_YS = (903, 1090, 1278, 1440)
    PASS_MARKER_YS = (903, 1090, 1278, 1460)  # milestone diamond, bright once reached

    def _is_new_store(self, retry: int = 1) -> bool:
        for _ in range(retry):
            if (self.image.is_visible('labels/store/growth_emporium', confidence=0.85, seconds=0, suppress=True) or
                    self.image.is_visible('labels/store/visiting_merchants', confidence=0.85, seconds=0,
                                          suppress=True)):
                return True
            self.wait(1)
        return False

    def _badges(self, region) -> list:
        """Centres of red ! badges inside region"""
        boxes = self.image.find_all_images('buttons/store/red_badge', confidence=0.88, region=region)
        return [(x + w // 2, y + h // 2) for x, y, w, h in boxes]

    def _clear_merchant_emporium(self) -> bool:
        for name, (x, y) in self.EMPORIUMS.items():
            badges = self._badges(self.BOTTOM_BADGE_REGION)
            if not any(abs(bx - (x + self.EMPORIUM_BADGE_DX)) < 40 for bx, _ in badges):
                continue
            logger.purple(f"    Checking {name}")
            self.controller.tap(x, y, seconds=3)
            self._clear_badged_tabs(name)
        return True

    def _clear_badged_tabs(self, emporium: str):
        """Open every tab with a red ! badge and collect what is free there"""
        handled = []
        for scroll in range(2):
            for _ in range(8):  # safety limit per tab-bar position
                pending = [b for b in self._badges(self.TAB_BADGE_REGION)
                           if all(abs(b[0] - h[0]) > 40 for h in handled)]
                if not pending:
                    break
                bx, by = pending[0]
                handled.append((bx, by))
                tx, ty = bx + self.TAB_FROM_BADGE[0], by + self.TAB_FROM_BADGE[1]
                self.controller.tap(tx, ty, seconds=3)
                self._collect_tab(emporium, tx, bx)
            # Some emporiums have more tabs off-screen to the right; look there once
            if scroll == 0 and emporium == 'Basic Emporium':
                self.controller.swipe(900, 1650, 200, 1650, 600, seconds=2)
                handled = []
            else:
                break

    def _collect_tab(self, emporium: str, tab_x: int, badge_x: int):
        if self._is_pass_tab(emporium, tab_x):
            self._collect_pass_rewards(badge_x)
        else:
            self._collect_free_deals()

    def _is_pass_tab(self, emporium: str, tab_x: int) -> bool:
        if self.image.find_image('labels/store/unlock_premium', confidence=0.8, grayscale=True,
                                 region=(0, 580, 400, 100)) is not None:
            return True
        # Premium pass already bought: Monthly Emporium tabs 2-4 are the passes
        return emporium == 'Monthly Emporium' and tab_x > 360

    def _collect_pass_rewards(self, badge_x: int):
        """Claim reached, unclaimed rewards in the free (Common) column of a pass"""
        logger.purple("    Collecting pass rewards (Common column)")
        tapped = set()
        for _ in range(3):
            screenshot = self.device.get_screenshot()
            gray = screenshot.convert('L')
            checks = self.image.find_all_images('buttons/store/claimed_check', confidence=0.85,
                                                region=(150, 820, 150, 680), screenshot=screenshot)
            new_taps = False
            for row_y, marker_y in zip(self.PASS_ROW_YS, self.PASS_MARKER_YS):
                reached = gray.getpixel((self.PASS_MARKER_X, marker_y)) > 180
                claimed = any(cy - 60 < row_y < cy + ch + 60 for _, cy, _, ch in checks)
                if reached and not claimed and row_y not in tapped:
                    tapped.add(row_y)
                    self.controller.tap(self.PASS_COMMON_X, row_y, seconds=2)
                    self.controller.tap(*self.DISMISS, seconds=1)
                    new_taps = True
            if not new_taps or not self._tab_still_badged(badge_x):
                break

    def _tab_still_badged(self, badge_x: int) -> bool:
        """True if the tab whose badge was at badge_x still shows a red !"""
        return any(abs(bx - badge_x) < 40 for bx, _ in self._badges(self.TAB_BADGE_REGION))

    def _collect_free_deals(self):
        """Tap only items whose price label is 'Free' - never a price button"""
        for page in range(2):
            tapped = []
            for _ in range(5):
                frees = [(x + w // 2, y + h // 2) for x, y, w, h in
                         self.image.find_all_images('buttons/store/free', confidence=0.88,
                                                    region=self.CONTENT_REGION)]
                # Each Free spot is tapped once per page, in case the label stays after claiming
                frees = [f for f in frees if all(abs(f[0] - t[0]) > 30 or abs(f[1] - t[1]) > 30 for t in tapped)]
                if not frees:
                    break
                fx, fy = frees[0]
                tapped.append((fx, fy))
                logger.purple("    Collecting free deal")
                self.controller.tap(fx, fy, seconds=3)
                self.controller.tap(*self.DISMISS, seconds=2)
            if page == 0:
                # Lower cards may be hidden behind the tab bar
                self.controller.swipe(540, 1300, 540, 800, 600, seconds=2)

    # ------------------------------------------------------------------
    # Old store layout (fallback)
    # ------------------------------------------------------------------

    def _clear_merchant_legacy(self) -> bool:
        """Old merchant flow; expects the merchant screen to be open already"""
        # Check for Fun in the Wild event
        if self.image.is_visible('buttons/funinthewild', click=True, seconds=2):
            self.controller.tap(250, 1820, seconds=2)  # Ticket
            self.controller.tap(250, 1820, seconds=2)  # Reward

        # Swipe to nobles section
        self.controller.swipe(1000, 1825, 100, 1825, 500)

        # Handle Noble Society
        if self.image.is_visible('buttons/noblesociety'):
            logger.purple("    Collecting Nobles")
            self.controller.tap(675, 1825)

            if self.image.is_visible('buttons/confirm_nobles', confidence=0.8, retry=2):
                logger.warning("Noble resource collection screen found, skipping Noble collection")
                self.controller.tap(70, 1810)
            else:
                # Champion rewards
                self.controller.tap(750, 1600)  # Icon
                self.controller.tap(440, 1470, seconds=0.5)
                self.controller.tap(440, 1290, seconds=0.5)
                self.controller.tap(440, 1100, seconds=0.5)
                self.controller.tap(440, 915, seconds=0.5)
                self.controller.tap(440, 725, seconds=0.5)
                self.controller.tap(750, 1600)  # Close icon

                # Twisted rewards
                self.controller.tap(600, 1600)  # Icon
                self.controller.tap(440, 1470, seconds=0.5)
                self.controller.tap(440, 1290, seconds=0.5)
                self.controller.tap(440, 1100, seconds=0.5)
                self.controller.tap(440, 915, seconds=0.5)
                self.controller.tap(440, 725, seconds=0.5)
                self.controller.tap(600, 1600)  # Close icon

                # Regal rewards
                self.controller.tap(450, 1600)  # Icon
                self.controller.tap(440, 1470, seconds=0.5)
                self.controller.tap(440, 1290, seconds=0.5)
                self.controller.tap(440, 1100, seconds=0.5)
                self.controller.tap(440, 915, seconds=0.5)
                self.controller.tap(440, 725, seconds=0.5)
                self.controller.tap(450, 1600)  # Close icon

            # Monthly Cards
            logger.purple("    Collecting Monthly Cards")
            self.controller.tap(180, 1600)

            # Monthly card
            self.controller.tap(300, 1000, seconds=3)
            self.controller.tap(560, 430)

            # Deluxe Monthly card
            self.controller.tap(850, 1000, seconds=3)
            self.controller.tap(560, 430)

        # Trade post
        if self.image.is_visible('buttons/tradepost', click=True):
            # Special Deal, no check as its active daily
            logger.purple("    Collecting Special Deal")
            self.image.click_image('buttons/dailydeals')
            self.controller.tap(150, 1625)
            self.controller.tap(150, 1625)
            
            # Daily Deal
            if self.image.is_visible('buttons/merchant_daily', confidence=0.8, retry=2, click=True):
                logger.purple("    Collecting Daily Deal")
                self.controller.swipe(550, 1400, 550, 1200, 500, seconds=3)
                self.image.click_image('buttons/dailydeals', confidence=0.8, retry=2)
                self.controller.tap(400, 1675, seconds=3)
            
            # Biweeklies (Wednesday only)
            import datetime
            if datetime.datetime.now().isoweekday() == 3:  # Wednesday
                if self.image.is_visible('buttons/merchant_biweekly', confidence=0.8, retry=2, click=True):
                    logger.purple("    Collecting Bi-weekly Deal")
                    self.controller.swipe(300, 1400, 200, 1200, 500, seconds=3)
                    self.controller.tap(200, 1200)
                    self.controller.tap(550, 1625, seconds=3)

        self.wait(1)
        self.controller.swipe(200, 1825, 450, 1825, 1000)
        self.wait(1)  # wait for the swipe to finish

        # Wishing Ship
        if self.image.is_visible('buttons/wishingship', click=True, seconds=2):
            # Yuexi (Monday only)
            import datetime
            if datetime.datetime.now().isoweekday() == 1:  # Monday
                logger.purple("    Collecting Yuexi")
                self.controller.tap(250, 1600)
                self.controller.tap(240, 880)
                self.controller.tap(150, 1625, seconds=2)
                self.controller.tap(950, 200)
                self.controller.tap(730, 1050)
                self.controller.tap(150, 1625, seconds=2)
                self.controller.tap(900, 400, seconds=2)
            
            # Clear Rhapsody bundles notification
            logger.purple("    Clearing Rhapsody bundles notification")
            self.controller.tap(620, 1600)
            self.controller.tap(980, 200)
            self.controller.tap(70, 1810)
            self.controller.tap(70, 1810)

        return True
