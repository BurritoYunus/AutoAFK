"""Guild activities implementation"""
import logging
from datetime import datetime, timezone
from src.activities.base_activity import BaseActivity

logger = logging.getLogger(__name__)


class GuildActivities(BaseActivity):
    """Handles guild activities"""

    # Guild Hunt building on the new guild "island" layout (bottom centre, 1080x1920)
    GUILD_HUNT_ISLAND = (558, 1340)
    # Guild Hunt building on the old guild layout, kept as a fallback
    GUILD_HUNT_LEGACY = (290, 860)

    def _in_guild_hunts(self, retry: int = 3) -> bool:
        """True if the Hunting Fields screen is showing"""
        for _ in range(retry):
            if (self.image.is_visible('buttons/challenge_tr', confidence=0.7, seconds=0, suppress=True) or
                    self.image.is_visible('labels/hunting_fields_contract', seconds=0, suppress=True)):
                return True
            self.wait(1)
        return False

    def _open_guild_hunts(self) -> bool:
        """Open Guild Hunts from the guild screen.

        Taps the Guild Hunt building on the new island layout first, checks that
        Hunting Fields opened, and falls back to the old building position if not.
        """
        for name, (x, y) in (('island', self.GUILD_HUNT_ISLAND),
                             ('legacy', self.GUILD_HUNT_LEGACY)):
            self.controller.tap(x, y, seconds=4)  # Guild Hunts building
            if self._in_guild_hunts(retry=2):
                self.controller.tap(300, 50)  # Clear popup (as before)
                logger.debug(f"    Guild Hunts opened via {name} position ({x}, {y})")
                return True
            # A popup may be covering Hunting Fields - clear it and check again
            self.controller.tap(300, 50)
            if self._in_guild_hunts(retry=2):
                logger.debug(f"    Guild Hunts opened via {name} position ({x}, {y})")
                return True
            logger.debug(f"    Guild Hunts not found after tapping {name} position ({x}, {y})")
        return False

    def handle_guild_hunts(self, skip_hf: bool = False) -> bool:
        """Handle Guild Hunts (Hunting Fields, Wrizz, Soren)"""
        logger.blue("Handling Guild Hunts...")
        
        self.controller.confirm_location('ranhorn', 
                                        region=self.controller.BOUNDARIES['ranhornSelect'])
        self.controller.tap(380, 360)
        self.wait(6)
        self.controller.tap(550, 1800)  # Clear chests
        
        # Collect guild reward chests
        self.image.click_image('buttons/guild_chests', seconds=2)
        if self.image.is_visible('buttons/collect_guildchest', click=True):
            self.controller.tap(550, 1300)
            self.controller.tap(900, 550)
            self.controller.tap(550, 1800)
            self.wait(1)
        else:
            self.controller.tap(550, 1800)
            
        self.controller.tap(20, 20)  # Clear popups
        if not self._open_guild_hunts():
            logger.warning("    Could not confirm Guild Hunts opened, continuing anyway")

        # Hunting Fields
        if not skip_hf:
            logger.green("    Trying to battle Hunting Fields")
            hf_ok = True
            current_day = datetime.now(timezone.utc).isoweekday()
            
            # Monday and Tuesday - copy formation from leaderboard
            if current_day in (1, 2):
                self.controller.tap(85, 140)  # Leaderboard
                
                if self.image.is_visible('buttons/detail', region=(912, 514, 100, 100), click=True, seconds=3):
                    self.controller.tap(230, 625)  # First attempt
                    self.controller.tap(90, 290)  # Copy formation
                    self.image.click_image('buttons/confirm', seconds=2, suppress=True)
                    self.controller.tap(300, 50)  # Clear popup
                    self.controller.tap(300, 50)  # Clear popup
                    self.image.click_image('buttons/back', seconds=2, retry=3)
                    
                    if self.image.is_visible('buttons/challenge_tr', confidence=0.7, retry=3, click=True, seconds=5):
                        self.controller.tap(70, 1090)  # Formations
                        
                        # Swipe down to copied formation
                        for _ in range(6):
                            self.controller.swipe(540, 1600, 540, 1200, duration=300, seconds=1)
                        
                        self.controller.tap(500, 1600, seconds=2)  # Select copied formation
                        self.controller.tap(600, 1100)  # 2nd team
                        self.wait(2)  # Wait for formation to load
                        
                        self.controller.long_press(620, 1650)  # Long press for options
                        self.image.click_image('buttons/delete_formation')
                        
                        if self.image.is_visible('buttons/battle_large', confidence=0.7, retry=3, click=True, seconds=5):
                            self.image.click_image('buttons/skip', retry=5, confidence=0.8, 
                                                  suppress=True, region=self.controller.BOUNDARIES['skipAoH'])
                            self.controller.tap(550, 1800)
                            hf_ok = True
                        else:
                            self.image.click_image('buttons/back')
                else:
                    logger.warning("    Nothing found on leaderboard, skipping...")
                    self.image.click_image('buttons/back', seconds=2, retry=3)
                    hf_ok = False
                    
            # Do 2 more HF battles
            if hf_ok:
                for _ in range(2):
                    if self.image.is_visible('buttons/challenge_tr', confidence=0.7, retry=3, click=True, seconds=5):
                        self.controller.tap(600, 1100)  # 2nd team
                        
                        if self.image.is_visible('buttons/battle_large', confidence=0.7, retry=3, click=True, seconds=5):
                            self.controller.tap(760, 1460, seconds=3)
                            self.controller.tap(550, 1800)
                        else:
                            self.image.click_image('buttons/back')
                            
            # Collect HF contract rewards
            if self.image.is_visible('labels/hunting_fields_contract'):
                while (self.image.is_visible('labels/hf_contract_done') and 
                       not self.image.is_visible('labels/hunting_fields_claimed')):
                    self.controller.tap(540, 1200)
                    self.controller.tap(550, 1800)
            else:
                logger.error("    Hunting Fields Contract screen not found, attempting to recover")
                self.controller.recover(silent=True)
                return self.handle_guild_hunts(skip_hf=True)
                
        # Next hunts
        self.controller.tap(970, 630)
        
        # Wrizz check
        if not self.image.is_visible('labels/wrizz', retry=3, suppress=True):
            self.wait(3)
            self.controller.tap(970, 630)
            self.wait(1)
            
        if self.image.is_visible('labels/wrizz'):
            if self.image.is_visible('buttons/quickbattle'):
                logger.green("    Wrizz found, collecting")
                self.image.click_image('buttons/quickbattle')
                self.controller.tap(725, 1300)
                
                # Handle capped resources screen
                if self.image.is_visible('buttons/confirm', click=True):
                    pass
                    
                self.controller.tap(550, 500)
                self.controller.tap(550, 500, seconds=2)
            else:
                logger.warning("    Wrizz quick battle not found")
                
            # Soren
            self.controller.tap(970, 630)
            
            # Soren activation (specific days)
            days_str = self.config.get('DAILIES', 'sorenactivate_days', fallback='1,2,3,4,5,6,7')
            activate_days = [int(day.strip()) for day in days_str.split(',')]
            current_day = datetime.now().isoweekday()  # Local time, same as old version
            
            if (self.config.getboolean('DAILIES', 'sorenactivate', fallback=False) and 
                current_day in activate_days):
                if (not self.image.is_visible('buttons/quickbattle') and 
                    self.image.is_visible('buttons/open', retry=3)):
                    self.controller.tap(540, 1830)  # Activate Soren
                    
                    if self.image.is_visible('buttons/confirm_soren', click=True):
                        logger.green("    Soren activated")
                    else:
                        self.controller.tap(100, 1700)  # Clear popup
                else:
                    logger.warning("    Soren already activated, skipping activation")
                    
            if self.image.is_visible('buttons/quickbattle'):
                logger.green("    Soren found, collecting")
                self.image.click_image('buttons/quickbattle')
                self.controller.tap(725, 1300)
                
                # Handle capped resources screen
                if self.image.is_visible('buttons/confirm', click=True):
                    pass
                    
                self.controller.tap(550, 500)
                self.controller.tap(550, 500, seconds=2)
            else:
                logger.warning("    Soren quick battle not found")
                
            self.controller.tap(70, 1810)
            self.controller.tap(70, 1810)
            logger.green("    Guild Hunts checked successfully")
        else:
            logger.error("    Wrizz not found, attempting to recover")
            self.controller.recover()
            return False
            
        self.controller.recover(silent=True)
        return True

