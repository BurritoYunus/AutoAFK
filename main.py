"""
AutoAFK - Modern modular architecture
Uses new modular backend with full functionality
"""
import os
import sys

# Text recognition (onnxruntime): never send usage data to Microsoft
os.environ.setdefault('ORT_DISABLE_TELEMETRY', '1')
import threading
import time
import datetime
import logging
import argparse
import subprocess
from pathlib import Path

# Version - Update this when releasing new version
VERSION = "2.1.0"

# GitHub Repository (updates are fetched from here)
GITHUB_REPO = "BurritoYunus/AutoAFK"
KOFI_URL = 'https://ko-fi.com/dolphinafk'
GITHUB_BRANCH = "master"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

try:
    import customtkinter as ctk
except ImportError:
    print("Installing customtkinter...")
    os.system("pip install customtkinter")
    import customtkinter as ctk

from src.core.config import Config
from src.core.device_manager import DeviceManager
from src.core.image_recognition import ImageRecognition
from src.core.game_controller import GameController
from src.core.activity_manager import ActivityManager
from src.core.dailies_runner import execute_dailies
from src.activities.tower_activities import TowerPusher
from src.utils.logger import Logger
from src.utils.notifications import NotificationManager
from src.utils.version_checker import VersionChecker

# Set appearance - Modern dark theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")  # Modern blue theme

logger = Logger.get_logger(__name__)

# Global args variable
args = None


def initialize_core_modules(config: Config) -> tuple:
    """Initialize core modules (device, image recognition, game controller)
    
    Args:
        config: Configuration instance
        
    Returns:
        tuple: (device_manager, image_recognition, game_controller) or (None, None, None) on failure
    """
    device_manager = DeviceManager(config)
    if not device_manager.connect():
        logger.error("Failed to connect to device")
        return None, None, None
        
    image_recognition = ImageRecognition(device_manager, config)
    game_controller = GameController(device_manager, image_recognition, config)
    
    # Enable automatic screenshots on errors
    from src.utils.logger import set_device_manager
    set_device_manager(device_manager)
    
    return device_manager, image_recognition, game_controller


class App(ctk.CTk):
    """Main application window - original style"""
    
    def __init__(self):
        super().__init__()
        
        # Window setup
        self.title(f"AutoAFK {VERSION}")
        self.geometry("800x540")
        self.resizable(False, False)  # Disable window resizing
        
        # Try to set icon
        icon_paths = [
            Path("img/auto.ico"),
            Path("_internal/img/auto.ico"),
            Path(sys._MEIPASS) / "img" / "auto.ico" if getattr(sys, 'frozen', False) else None
        ]
        
        for icon_path in icon_paths:
            if icon_path and icon_path.exists():
                try:
                    self.iconbitmap(str(icon_path))
                    break
                except:
                    pass
        
        # Config and core modules
        self.config = Config('settings.ini')
        
        # Initialize Logger
        from src.utils.logger import Logger as LoggerClass
        LoggerClass()  # Initialize logger singleton
        
        self.device_manager = None
        self.image_recognition = None
        self.game_controller = None
        self.daily_activities = None
        self.arena_activities = None
        self.legacy_activities = None
        self.notification_manager = None
        
        # Thread state
        self.dailies_thread_running = False
        self.activity_thread_running = False
        self.push_thread_running = False
        
        self.dailies_thread = None
        self.activity_thread = None
        self.push_thread = None
        
        self.dailies_stop_event = threading.Event()
        self.activity_stop_event = threading.Event()
        self.push_stop_event = threading.Event()
        
        self.dailies_pause_event = threading.Event()
        self.activity_pause_event = threading.Event()
        self.push_pause_event = threading.Event()
        
        # Windows
        self.shop_window = None
        self.activity_window = None
        self.advanced_window = None
        
        self._create_widgets()
        
    def _check_for_updates(self) -> None:
        """Check for updates in background thread to avoid blocking UI"""
        def check():
            try:
                update_available, current, latest = VersionChecker.check_for_updates()
                notes = VersionChecker.get_release_notes(latest) if (latest and update_available) else None

                def update_ui():
                    if not latest:
                        self.textbox.insert('end', '⚠️ Could not check for updates\n\n', 'warning')
                        return

                    if not update_available:
                        return

                    self.textbox.insert('end', '⚠️ UPDATE AVAILABLE!\n', 'yellow')
                    self.textbox.insert('end', f'Current version: {current}\n', 'warning')
                    self.textbox.insert('end', f'Latest version: {latest}\n\n', 'yellow')

                    if notes:
                        self.textbox.insert('end', f'Version {latest} changes:\n', 'yellow')
                        self.textbox.insert('end', f'{notes[:500]}{"..." if len(notes) > 500 else ""}\n\n', 'warning')

                    installed = self._installed_release_version()
                    if installed and installed == latest:
                        # The updater already installed this release but the app still
                        # reports an older VERSION: updating again would loop forever.
                        self.textbox.insert('end', f'⚠️ Version {latest} is already installed but this build reports {current}. '
                                                   'Skipping auto-update to avoid a loop.\n\n', 'warning')
                    elif self.config.getboolean('ADVANCED', 'autoupdate', fallback=False):
                        self.textbox.insert('end', '🔄 Auto-update enabled, starting updater...\n\n', 'orange')
                        self.after(2000, self._run_updater)
                    else:
                        self.textbox.insert('end', '💡 Run update.bat to update or download from:\n', 'blue')
                        self.textbox.insert('end', f'{VersionChecker.get_download_url()}\n\n', 'blue')

                self.after(0, update_ui)
            except Exception as e:
                logger.debug(f"Version check failed: {e}")

        threading.Thread(target=check, daemon=True).start()
    
    @staticmethod
    def _installed_release_version():
        """Version the updater last installed (from .installed_version), if any"""
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
            else os.path.dirname(os.path.abspath(__file__))
        try:
            with open(os.path.join(base_dir, '.installed_version'), encoding='utf-8') as f:
                return f.read().strip() or None
        except OSError:
            return None

    def _open_link(self, event) -> None:
        """Open URL in browser when clicked"""
        import webbrowser
        
        # Get all tags at click position
        tags = self.textbox.tag_names(f"@{event.x},{event.y}")
        
        # Find URL from stored links
        for tag in tags:
            if tag in self.link_urls:
                webbrowser.open(self.link_urls[tag])
                break
    
    def _get_tower_options_for_today(self) -> list:
        """Get available tower options based on day of week (UTC timezone)"""
        from datetime import datetime, timezone
        
        # Get current day in UTC (1=Monday, 7=Sunday)
        # Game uses UTC timezone for tower resets
        current_day = datetime.now(timezone.utc).isoweekday()
        
        # Tower availability by day
        tower_days = {
            1: ["Campaign", "King's Tower", "Lightbearer Tower"],
            2: ["Campaign", "King's Tower", "Mauler Tower"],
            3: ["Campaign", "King's Tower", "Wilder Tower", "Celestial Tower"],
            4: ["Campaign", "King's Tower", "Graveborn Tower", "Hypogean Tower"],
            5: ["Campaign", "King's Tower", "Lightbearer Tower", "Mauler Tower", "Celestial Tower"],
            6: ["Campaign", "King's Tower", "Wilder Tower", "Graveborn Tower", "Hypogean Tower"],
            7: ["Campaign", "King's Tower", "Lightbearer Tower", "Wilder Tower", "Mauler Tower", 
                "Graveborn Tower", "Hypogean Tower", "Celestial Tower"]
        }
        
        return tower_days.get(current_day, ["Campaign", "King's Tower"])
    
    def _run_updater(self) -> None:
        """Launch updater as a detached process with its own visible console window"""
        try:
            # Resolve base directory (works for both frozen exe and script)
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))

            updater_exe = os.path.join(base_dir, '_internal', 'AutoAFKUpdater.exe')
            updater_py = os.path.join(base_dir, 'AutoAFKUpdater.py')

            if os.path.exists(updater_exe):
                cmd = [updater_exe, '--auto']
            elif os.path.exists(updater_py):
                cmd = [sys.executable, updater_py, '--auto']
            else:
                self.textbox.insert('end', '❌ Updater not found\n', 'error')
                return

            # Launch in a new visible console window, fully detached from this process
            # CREATE_NEW_CONSOLE gives user a window to see progress
            # CREATE_NEW_PROCESS_GROUP ensures it survives when AutoAFK.exe is killed
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            )

            self.textbox.insert('end', '🔄 Updater started in separate window\n', 'orange')
            self.textbox.insert('end', '⏳ Bot will close in 5 seconds...\n', 'orange')
            self.textbox.see('end')
            self.after(5000, self.quit)

        except Exception as e:
            self.textbox.insert('end', f'❌ Failed to run updater: {e}\n', 'error')
        
    def _create_widgets(self) -> None:
        """Create all widgets - original layout"""
        
        # Dailies Frame
        self.dailiesFrame = ctk.CTkFrame(master=self, height=170, width=180)
        self.dailiesFrame.place(x=10, y=20)
        
        self.dailiesButton = ctk.CTkButton(
            master=self.dailiesFrame,
            text="Run Dailies",
            command=self.start_dailies_thread
        )
        self.dailiesButton.place(x=20, y=10)
        
        self.activitiesButton = ctk.CTkButton(
            master=self.dailiesFrame,
            text="Configure Dailies",
            fg_color=["#343638", "#343638"],  # Match dropdown menu color
            hover_color=["#3E4042", "#3E4042"],
            width=120,
            command=self.open_activitywindow
        )
        self.activitiesButton.place(x=30, y=50)
        
        self.dailiesShopButton = ctk.CTkButton(
            master=self.dailiesFrame,
            text="Store Options",
            fg_color=["#343638", "#343638"],  # Match dropdown menu color
            hover_color=["#3E4042", "#3E4042"],
            width=120,
            command=self.open_shopwindow
        )
        self.dailiesShopButton.place(x=30, y=90)
        
        self.advancedButton = ctk.CTkButton(
            master=self.dailiesFrame,
            text="Advanced Options",
            fg_color=["#343638", "#343638"],  # Match dropdown menu color
            hover_color=["#3E4042", "#3E4042"],
            width=120,
            command=self.open_advancedwindow
        )
        self.advancedButton.place(x=30, y=130)
        
        # PvP Frame
        self.arenaFrame = ctk.CTkFrame(master=self, height=130, width=180)
        self.arenaFrame.place(x=10, y=200)
        
        self.arenaButton = ctk.CTkButton(
            master=self.arenaFrame,
            text="Run Activity",
            command=self.start_activity_thread
        )
        self.arenaButton.place(x=20, y=15)
        
        self.activityFormationDropdown = ctk.CTkComboBox(
            master=self.arenaFrame,
            values=[
                "Arena of Heroes",
                "Arcane Labyrinth",
                "Fight of Fates",
                "Battle of Blood",
                "Heroes of Esperia",
                "Guild Hunts",
                "Misty Valley",
                "Shadow Realm"
            ],
            width=160,
            command=self._on_activity_selected
        )
        self.activityFormationDropdown.place(x=10, y=55)
        
        self.pvpLabel = ctk.CTkLabel(
            master=self.arenaFrame,
            text='How many battles?'
        )
        self.pvpLabel.place(x=10, y=90)
        
        self.pvpEntry = ctk.CTkEntry(master=self.arenaFrame, height=20, width=40)
        self.pvpEntry.insert('end', self.config.get('ACTIVITIES', 'arena_battles', fallback='5'))
        self.pvpEntry.place(x=130, y=92)
        self._on_activity_selected(self.activityFormationDropdown.get())
        
        # Push Frame
        self.pushFrame = ctk.CTkFrame(master=self, height=180, width=180)
        self.pushFrame.place(x=10, y=340)
        
        self.pushButton = ctk.CTkButton(
            master=self.pushFrame,
            text="Auto Push",
            command=self.start_push_thread
        )
        self.pushButton.place(x=20, y=10)
        
        # Set tower options based on day of week
        tower_values = self._get_tower_options_for_today()
        
        self.pushLocationDropdown = ctk.CTkComboBox(
            master=self.pushFrame,
            values=tower_values,
            width=160
        )
        self.pushLocationDropdown.place(x=10, y=50)
        
        self.pushLabel = ctk.CTkLabel(
            master=self.pushFrame,
            text='Which formation?'
        )
        self.pushLabel.place(x=10, y=80)
        
        self.pushFormationDropdown = ctk.CTkComboBox(
            master=self.pushFrame,
            values=["1st", "2nd", "3rd", "4th", "5th"],
            width=80
        )
        # Load saved formation from config
        saved_formation_str = self.config.get('PUSH', 'formation', fallback='3')
        # Parse formation - handle both "3" and "3rd" formats
        if saved_formation_str.isdigit():
            saved_formation = int(saved_formation_str)
        else:
            # Extract number from "3rd" format
            saved_formation = int(saved_formation_str[0])
        formation_map = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
        self.pushFormationDropdown.set(formation_map.get(saved_formation, "3rd"))
        self.pushFormationDropdown.place(x=10, y=110)
        
        # Textbox - Modern styling
        self.textbox = ctk.CTkTextbox(master=self, width=580, height=500)
        self.textbox.place(x=200, y=20)
        self.textbox.configure(
            text_color='#E8E8E8',           # Soft white
            fg_color='#1E1E1E',             # Dark background
            font=('Segoe UI', 13),          # Modern font
            border_width=2,
            border_color='#3A3A3A'          # Subtle border
        )
        
        # Configure tags - Modern minimalist color scheme
        self.textbox.tag_config("error", foreground="#EF4444")      # Bright red
        self.textbox.tag_config('warning', foreground="#F59E0B")    # Amber
        self.textbox.tag_config('green', foreground="#10B981")      # Emerald green
        self.textbox.tag_config('blue', foreground="#3B82F6")       # Blue
        self.textbox.tag_config('purple', foreground="#A855F7")     # Purple
        self.textbox.tag_config('yellow', foreground="#F59E0B")     # Amber
        self.textbox.tag_config('orange', foreground="#F97316")     # Orange
        self.textbox.tag_config('dim', foreground="#9CA3AF")        # Grey (less important lines)
        self.textbox.tag_config('silver', foreground="#CBD5E1")     # Silver
        self.textbox.tag_config('gold', foreground="#FBBF24")       # Gold
        
        # Configure clickable link tags
        self.textbox.tag_config('link', foreground="#3B82F6", underline=True)
        self.textbox.tag_bind('link', '<Button-1>', self._open_link)
        self.textbox.tag_bind('link', '<Enter>', lambda e: self.textbox.configure(cursor='hand2'))
        self.textbox.tag_bind('link', '<Leave>', lambda e: self.textbox.configure(cursor=''))
        
        # Store URLs for links
        self.link_urls = {}
        
        # Welcome message
        self.textbox.insert('end', f'AutoAFK {VERSION}\n', 'green')
        self.textbox.insert('end', '🔗 GitHub: ', 'info')
        
        # GitHub link (clickable)
        github_url = f'https://github.com/{GITHUB_REPO}'
        start_idx = self.textbox.index('end-1c')
        self.textbox.insert('end', f'{github_url}\n', 'link')
        end_idx = self.textbox.index('end-1c')
        github_tag = f'github_link_{id(github_url)}'
        self.textbox.tag_add(github_tag, start_idx, end_idx)
        self.link_urls[github_tag] = github_url

        # Ko-fi link (clickable)
        self.textbox.insert('end', '☕ Support: ', 'info')
        start_idx = self.textbox.index('end-1c')
        self.textbox.insert('end', f'{KOFI_URL}\n', 'link')
        end_idx = self.textbox.index('end-1c')
        self.textbox.tag_add('kofi_link', start_idx, end_idx)
        self.link_urls['kofi_link'] = KOFI_URL
        self.textbox.insert('end', '\n')
        
        # Check for updates
        self._check_for_updates()
        
        # Pause/Stop buttons
        self.pauseButton = ctk.CTkButton(
            master=self,
            text="⏸️",
            bg_color="#3B3B3B",
            fg_color="#1F6AA5",
            width=40,
            command=self.pause_all_thread,
            state="disabled",
            hover=False
        )
        self.pauseButton.place(x=690, y=25)
        self.pauseButton.place_forget()
        
        self.quitButton = ctk.CTkButton(
            master=self,
            text="⏹️",
            bg_color="#3B3B3B",
            fg_color=["#B60003", "#C03335"],
            width=40,
            command=self.stop_all_threads,
            state="disabled",
            hover=False
        )
        self.quitButton.place(x=735, y=25)
        self.quitButton.place_forget()
        
        # Setup logging redirect
        sys.stdout = STDOutRedirector(self.textbox)
        sys.stderr = STDOutRedirector(self.textbox)  # Also redirect errors
        
        # Redirect logger to GUI
        self._setup_logger_redirect()
        
        # Setup cleanup on close
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
    def _setup_logger_redirect(self) -> None:
        """Redirect logger output to GUI"""
        
        class GUIHandler(logging.Handler):
            def __init__(self, app):
                super().__init__()
                self.app = app
                
            def emit(self, record):
                try:
                    msg = self.format(record)
                    timestamp = '[' + datetime.datetime.now().strftime("%H:%M:%S") + '] '
                    
                    # Import custom levels
                    from src.utils.logger import BLUE, GREEN, PURPLE
                    
                    # A colour picked by the caller (extra={'tag': ...}) wins
                    tag = getattr(record, 'tag', None)
                    if tag:
                        self.app.textbox.insert('end', timestamp + msg + '\n', tag)
                    # Color based on level - check custom levels first
                    elif record.levelno == GREEN:
                        self.app.textbox.insert('end', timestamp + msg + '\n', 'green')
                    elif record.levelno == BLUE:
                        self.app.textbox.insert('end', timestamp + msg + '\n', 'blue')
                    elif record.levelno == PURPLE:
                        self.app.textbox.insert('end', timestamp + msg + '\n', 'purple')
                    elif record.levelno >= logging.ERROR:
                        self.app.textbox.insert('end', timestamp + msg + '\n', 'error')
                    elif record.levelno >= logging.WARNING:
                        self.app.textbox.insert('end', timestamp + msg + '\n', 'warning')
                    elif record.levelno >= logging.INFO:
                        # Color INFO messages based on content
                        if 'collected' in msg.lower() or 'completed' in msg.lower() or 'success' in msg.lower():
                            self.app.textbox.insert('end', timestamp + msg + '\n', 'green')
                        elif 'starting' in msg.lower() or 'attempting' in msg.lower():
                            self.app.textbox.insert('end', timestamp + msg + '\n', 'blue')
                        else:
                            self.app.textbox.insert('end', timestamp + msg + '\n')
                    else:
                        self.app.textbox.insert('end', timestamp + msg + '\n')
                        
                    self.app.textbox.see('end')
                    self.app.update_idletasks()
                    
                    # Send to Discord if enabled
                    if hasattr(self.app, 'notification_manager') and self.app.notification_manager:
                        level_name = logging.getLevelName(record.levelno)
                        self.app.notification_manager.send(msg, level_name)
                except:
                    pass  # Ignore errors during logging
                
        # Add handler to root logger
        handler = GUIHandler(self)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
    
    def _on_closing(self) -> None:
        """Cleanup when closing the application"""
        try:
            # Stop all threads
            self.stop_all_threads()
            
            # Cleanup ADB synchronously to ensure it completes
            try:
                if self.device_manager:
                    logger.info("Disconnecting and cleaning up ADB...")
                    self.device_manager.disconnect()
                    self.device_manager._kill_adb_processes()
                    # Give it a moment to complete
                    import time
                    time.sleep(0.5)
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")
            
        except Exception as e:
            logger.debug(f"Cleanup error: {e}")
        finally:
            # Close the window
            self.destroy()
    
    def start_dailies_thread(self) -> None:
        """Start dailies thread"""
        if not self.dailies_thread_running:
            self.dailies_thread_running = True
            self.dailies_stop_event.clear()
            self.dailies_pause_event.clear()
            self.dailies_thread = threading.Thread(target=self.dailies)
            self.dailies_thread.start()
            self.button_state('disabled')
            self.stop_button_state('normal')
            
    def start_activity_thread(self) -> None:
        """Start activity thread"""
        if not self.activity_thread_running:
            self.activity_thread_running = True
            self.activity_stop_event.clear()
            self.activity_pause_event.clear()
            self.activity_thread = threading.Thread(target=self.activity_manager)
            self.activity_thread.start()
            self.button_state('disabled')
            self.stop_button_state('normal')
            
    def start_push_thread(self) -> None:
        """Start push thread"""
        if not self.push_thread_running:
            self.push_thread_running = True
            self.push_stop_event.clear()
            self.push_pause_event.clear()
            self.push_thread = threading.Thread(target=self.push)
            self.push_thread.start()
            self.button_state('disabled')
            self.stop_button_state('normal')

            
    def stop_all_threads(self) -> None:
        """Stop all threads"""
        print('WAR' + "Stop pressed, stopping after current action")
        self.dailies_thread_running = False
        self.activity_thread_running = False
        self.push_thread_running = False
        
        self.dailies_stop_event.set()
        self.activity_stop_event.set()
        self.push_stop_event.set()
        
    def pause_all_thread(self) -> None:
        """Pause all threads"""
        print('WAR' + "Pause pressed, pausing after current action")
        self.dailies_pause_event.set()
        self.activity_pause_event.set()
        self.push_pause_event.set()
        self.pauseButton.configure(text="▶️", command=self.resume_all_thread, fg_color="green")
        self.quitButton.configure(state='disabled')
        
    def resume_all_thread(self) -> None:
        """Resume all threads"""
        self.dailies_pause_event.clear()
        self.activity_pause_event.clear()
        self.push_pause_event.clear()
        self.pauseButton.configure(text="⏸️", command=self.pause_all_thread, fg_color="#1F6AA5")
        self.quitButton.configure(state='normal')
        
    def button_state(self, state: str) -> None:
        """Set button states"""
        self.dailiesButton.configure(state=state)
        self.arenaButton.configure(state=state)
        self.pushButton.configure(state=state)
        if state == 'normal':
            self.pauseButton.configure(state='disabled')
            self.quitButton.configure(state='disabled')
            self.pauseButton.place_forget()
            self.quitButton.place_forget()
            
    def stop_button_state(self, state: str) -> None:
        """Set stop button state"""
        if state == "normal":
            self.pauseButton.place(x=690, y=25)
            self.quitButton.place(x=735, y=25)
            self.pauseButton.lift()
            self.quitButton.lift()
        self.pauseButton.configure(state=state)
        self.quitButton.configure(state=state)
        
    def dailies(self) -> None:
        """Run dailies"""
        try:
            logger.info("Starting dailies...")
            
            # Initialize notification manager
            self.notification_manager = NotificationManager(self.config)
            
            # Initialize core modules
            self.device_manager, self.image_recognition, self.game_controller = \
                initialize_core_modules(self.config)
            
            if not self.device_manager:
                return
            
            # Initialize activity manager
            self.activity_manager = ActivityManager(
                self.device_manager, self.image_recognition, self.game_controller,
                self.config, self.notification_manager
            )
            
            # Execute dailies using shared function
            execute_dailies(self.activity_manager, self.dailies_pause_event, self.dailies_stop_event)
            
        except Exception as e:
            logger.error(f"Dailies error: {e}", exc_info=True)
        finally:
            self.dailies_thread_running = False
            self.button_state('normal')
            
    # Activities that don't use the battle count, with the hint shown instead
    ACTIVITY_HINTS = {
        "Arcane Labyrinth": "Clears the whole labyrinth",
        "Guild Hunts": "Runs today's hunts",
        "Misty Valley": "Clears all open stages",
        "Shadow Realm": "Uses all team attempts",
    }

    def _on_activity_selected(self, activity: str) -> None:
        """Only show "How many battles?" for activities that use it"""
        hint = self.ACTIVITY_HINTS.get(activity)
        if hint:
            self.pvpLabel.configure(text=hint)
            self.pvpEntry.place_forget()
        else:
            self.pvpLabel.configure(text='How many battles?')
            self.pvpEntry.place(x=130, y=92)

    def activity_manager(self) -> None:
        """Run selected activity"""
        try:
            activity = self.activityFormationDropdown.get()
            if activity in self.ACTIVITY_HINTS:
                battles = 0
                logger.info(f"Starting {activity}...")
            else:
                battles = int(self.pvpEntry.get())
                # Save battles count to config
                self.config.set('ACTIVITIES', 'arena_battles', str(battles))
                self.config.save()
                logger.info(f"Starting {activity} ({battles} battles)...")
            
            # Initialize modules if not already done
            if not self.device_manager:
                self.notification_manager = NotificationManager(self.config)
                
                # Initialize core modules
                self.device_manager, self.image_recognition, self.game_controller = \
                    initialize_core_modules(self.config)
                
                if not self.device_manager:
                    logger.error("Failed to connect to device")
                    return
            
            # Initialize activity manager with all modules
            activity_mgr = ActivityManager(
                self.device_manager, self.image_recognition, self.game_controller,
                self.config, self.notification_manager
            )
            
            # Expand menus and wait for game
            self.game_controller.expand_menus()
            self.game_controller.wait_until_game_active()
            
            logger.info("Device connected, running activity...")
            
            # Run specific activity
            result = None
            if activity == "Arena of Heroes":
                activity_mgr.arena.battle_arena_of_heroes(battles, 1, 
                                                         self.activity_pause_event,
                                                         self.activity_stop_event)
            elif activity == "Arcane Labyrinth":
                activity_mgr.labyrinth.handle_labyrinth()
            elif activity == "Fight of Fates":
                activity_mgr.misc.handle_fight_of_fates(battles)
            elif activity == "Battle of Blood":
                activity_mgr.misc.handle_battle_of_blood(battles)
            elif activity == "Heroes of Esperia":
                activity_mgr.misc.handle_heroes_of_esperia(battles, 4)
            elif activity == "Guild Hunts":
                activity_mgr.guild.handle_guild_hunts()
            elif activity == "Misty Valley":
                result = activity_mgr.misty.run(self.activity_stop_event, self.activity_pause_event)
            elif activity == "Shadow Realm":
                result = activity_mgr.shadow.run(self.activity_stop_event, self.activity_pause_event)

            if self.activity_stop_event.is_set():
                logger.warning("Activity stopped")
            elif result is False:
                logger.warning(f"{activity} stopped before finishing (see the messages above)")
            else:
                logger.info("Activity completed!")
        except Exception as e:
            logger.error(f"Activity error: {e}", exc_info=True)
        finally:
            self.activity_thread_running = False
            self.button_state('normal')
            
    def push(self) -> None:
        """Run push"""
        try:
            location = self.pushLocationDropdown.get()
            formation = int(self.pushFormationDropdown.get()[0])
            
            # Save formation to config
            self.config.set('PUSH', 'formation', str(formation))
            self.config.save()
            
            logger.info(f"Auto-Pushing {location} using formation {formation}")
            
            # Initialize modules if not already done
            if not self.device_manager:
                self.notification_manager = NotificationManager(self.config)
                
                # Initialize core modules
                self.device_manager, self.image_recognition, self.game_controller = \
                    initialize_core_modules(self.config)
                
                if not self.device_manager:
                    logger.error("Failed to connect to device")
                    return
            
            # Expand menus and wait for game
            self.game_controller.expand_menus()
            self.game_controller.wait_until_game_active()
            
            logger.info("Device connected, starting push...")
            
            # Get duration from config
            duration = self.config.getint('PUSH', 'victoryCheck', fallback=1)
            
            # Create TowerPusher and run
            from src.activities.tower_activities import TowerPusher
            pusher = TowerPusher(self.device_manager, self.image_recognition, 
                                self.game_controller, self.config, self.notification_manager)
            
            if "Tower" in location:
                # Push tower
                pusher.push_tower(location, formation, duration, 
                                 pause_event=self.push_pause_event,
                                 stop_event=self.push_stop_event)
            else:
                # Push campaign
                pusher.push_campaign(formation, duration,
                                    pause_event=self.push_pause_event,
                                    stop_event=self.push_stop_event)
            
            logger.info("Push completed!")
            
        except Exception as e:
            logger.error(f"Push error: {e}", exc_info=True)
        finally:
            self.push_thread_running = False
            self.button_state('normal')
            
    def open_advancedwindow(self) -> None:
        """Open advanced window"""
        if self.advanced_window is None or not self.advanced_window.winfo_exists():
            self.advanced_window = AdvancedWindow(self)
            self.advanced_window.focus()
        else:
            self.advanced_window.focus()
            
    def open_shopwindow(self) -> None:
        """Open shop window"""
        if self.shop_window is None or not self.shop_window.winfo_exists():
            self.shop_window = ShopWindow(self)
            self.shop_window.focus()
        else:
            self.shop_window.focus()
            
    def open_activitywindow(self) -> None:
        """Open activity window"""
        if self.activity_window is None or not self.activity_window.winfo_exists():
            self.activity_window = ActivityWindow(self)
            self.activity_window.focus()
        else:
            self.activity_window.focus()


class ActivityWindow(ctk.CTkToplevel):
    """Activity configuration window.

    Laid out with grid instead of fixed pixel positions, so it works with Windows display scaling:
    the window can be resized, the sections reflow into 3/2/1 columns, the body scrolls when it
    doesn't fit, and the Save button stays visible at the bottom.
    """

    SECTION_WIDTH = 250  # px per column before the layout drops to fewer columns

    def __init__(self, parent):
        super().__init__(parent)
        self.title('Dailies Configuration')
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.minsize(300, 300)

        self.config = parent.config
        self.activity_widgets = {}
        self.arena_widgets = {}
        self.events_widgets = {}
        self.bounties_widgets = {}

        activities = [
            ("Collect AFK Rewards", "checkbox", "collectRewards", "DAILIES"),
            ("Collect Mail", "checkbox", "collectMail", "DAILIES"),
            ("Companion Points", "checkbox", "companionPoints", "DAILIES"),
            ("Auto lend mercs?", "checkbox", "lendMercs", "DAILIES", True),
            ("Fast Rewards", "entry", "fastrewards", "DAILIES"),
            ("Attempt Campaign", "checkbox", "attemptCampaign", "DAILIES"),
            ("Fountain of Time", "checkbox", "fountainOfTime", "DAILIES"),
            ("King's Tower", "checkbox", "kingsTower", "DAILIES"),
            ("Collect Inn Gifts", "checkbox", "collectInn", "DAILIES"),
            ("Guild Hunts", "checkbox", "guildHunt", "DAILIES"),
            ("Store Purchases", "checkbox", "storePurchases", "DAILIES"),
            ("Shop Refreshes", "entry", "shoprefreshes", "DAILIES", True),
            ("Twisted Realm", "checkbox", "twistedRealm", "DAILIES"),
            ("Run Lab", "checkbox", "runLab", "DAILIES"),
            ("Collect Quests", "checkbox", "collectQuests", "DAILIES"),
            ("Collect Merchants", "checkbox", "collectMerchants", "DAILIES"),
            ("Use Bag Consumables", "checkbox", "useBagConsumables", "DAILIES"),
        ]
        arena_items = [
            ("Battle Arena of Heroes", "checkbox", "battleArena", "ARENA"),
            ("Number of Battles", "entry", "arenaBattles", "ARENA", True),
            ("Which Opponent", "entry", "arenaOpponent", "ARENA", True),
            ("Collect Daily TS loot", "checkbox", "tsCollect", "ARENA"),
            ("Collect Gladiator Coins", "checkbox", "gladiatorCollect", "ARENA"),
        ]
        events_items = [
            ("Fight of Fates", "checkbox", "fightOfFates", "EVENTS"),
            ("Battle of Blood", "checkbox", "battleOfBlood", "EVENTS"),
            ("Circus Tour", "checkbox", "circusTour", "EVENTS"),
            ("Heroes of Esperia", "checkbox", "heroesOfEsperia", "EVENTS"),
        ]
        bounties_items = [
            ("Enable solo bounties", "checkbox", "dispatchSoloBounties", "BOUNTIES"),
            ("Enable team bounties", "checkbox", "dispatchTeamBounties", "BOUNTIES"),
            ("Dispatch Dust", "checkbox", "dispatchDust", "BOUNTIES"),
            ("Dispatch Diamonds", "checkbox", "dispatchDiamonds", "BOUNTIES"),
            ("Dispatch Shards", "checkbox", "dispatchShards", "BOUNTIES"),
            ("Dispatch Juice", "checkbox", "dispatchJuice", "BOUNTIES"),
            ("Number of Refreshes", "entry", "refreshes", "BOUNTIES"),
            ("# Remaining to Dispatch All", "entry", "remaining", "BOUNTIES"),
            ("Enable event bounties", "checkbox", "dispatchEventBounties", "BOUNTIES"),
        ]
        misc_items = [
            ("Delay start by x minutes", "entry", "delayedstart", "DAILIES"),
            ("Hibernate system when done", "checkbox", "hibernate", "DAILIES"),
        ]

        # Body scrolls if the window is too small; the Save bar below it is always visible
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(master=self, fg_color="transparent")
        self.body.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 0))
        # one container per column (created before the sections so they draw on top of it);
        # sections are packed into whichever column the current layout puts them in
        self.columns = [ctk.CTkFrame(master=self.body, fg_color="transparent") for _ in range(3)]

        self.sections = [
            self._section("Activities:", activities, self.activity_widgets, entry_default='0'),
            self._section("Arena:", arena_items, self.arena_widgets, entry_default='5'),
            self._section("Events:", events_items, self.events_widgets),
            self._section("Bounties:", bounties_items, self.bounties_widgets, entry_default='0'),
            self._section("Misc:", misc_items, self.activity_widgets, entry_default='0'),
        ]

        bar = ctk.CTkFrame(master=self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=10)
        bar.grid_columnconfigure(0, weight=1)
        self.activitySaveButton = ctk.CTkButton(
            master=bar,
            text="Save",
            fg_color=["#10B981", "#059669"],
            hover_color=["#059669", "#047857"],
            width=140,
            command=self.activity_save
        )
        self.activitySaveButton.grid(row=0, column=0)

        self._columns = None
        self._reflow(3)
        self.body.bind("<Configure>", self._on_resize, add="+")

        # Start at the size the content needs, but never larger than the screen
        self.update_idletasks()
        scale = ctk.ScalingTracker.get_window_scaling(self) if hasattr(ctk, "ScalingTracker") else 1.0
        need_w = int((3 * self.SECTION_WIDTH + 60) * scale)
        content_h = max(c.winfo_reqheight() for c in self.columns)  # tallest column, already in real pixels
        need_h = content_h + int(90 * scale)                           # + Save bar and padding
        w = min(need_w, self.winfo_screenwidth() - 40)
        h = min(need_h, self.winfo_screenheight() - 120)
        self.geometry(f"{int(w / scale)}x{int(h / scale)}")

    def _section(self, title, items, store, entry_default='0'):
        """One titled box with a label + checkbox/entry per row"""
        frame = ctk.CTkFrame(master=self.body)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(master=frame, text=title, font=("Arial", 15, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 4))
        for row, item in enumerate(items, start=1):
            label_text, widget_type, config_key, section = item[:4]
            indent = len(item) > 4 and item[4]
            ctk.CTkLabel(master=frame, text=label_text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(40 if indent else 10, 6), pady=2)
            if widget_type == "checkbox":
                widget = ctk.CTkCheckBox(master=frame, text="", width=24, onvalue=True, offvalue=False)
                if self.config.getboolean(section, config_key, fallback=False):
                    widget.select()
            else:
                widget = ctk.CTkEntry(master=frame, height=24, width=40, justify="center")
                widget.insert('end', self.config.get(section, config_key, fallback=entry_default))
            widget.grid(row=row, column=1, sticky="e", padx=(0, 10), pady=2)
            store[config_key] = widget
        ctk.CTkFrame(master=frame, height=6, fg_color="transparent").grid(row=len(items) + 1, column=0)
        return frame

    def _on_resize(self, event):
        scale = ctk.ScalingTracker.get_window_scaling(self) if hasattr(ctk, "ScalingTracker") else 1.0
        cols = max(1, min(3, int(event.width / scale) // self.SECTION_WIDTH))
        self._reflow(cols)

    def _reflow(self, cols):
        """3 columns: Activities | Arena+Events | Bounties+Misc. Fewer columns stack the rest."""
        if cols == self._columns:
            return
        self._columns = cols
        layout = {3: [[0], [1, 2], [3, 4]], 2: [[0], [1, 2, 3, 4]], 1: [[0, 1, 2, 3, 4]]}[cols]
        for section in self.sections:
            section.pack_forget()
        for c, column in enumerate(self.columns):
            self.body.grid_columnconfigure(c, weight=1 if c < cols else 0, uniform="col" if c < cols else "")
            if c < cols:
                column.grid(row=0, column=c, sticky="new")
            else:
                column.grid_remove()
        for col, idxs in enumerate(layout):
            for i in idxs:
                self.sections[i].pack(in_=self.columns[col], fill="x", padx=5, pady=5)
                self.sections[i].lift()

    def activity_save(self) -> None:
        """Save all settings"""
        for config_key, widget in self.activity_widgets.items():
            if isinstance(widget, ctk.CTkCheckBox):
                self.config.set('DAILIES', config_key, 'True' if widget.get() else 'False')
            else:
                self.config.set('DAILIES', config_key, widget.get())
                
        for config_key, widget in self.arena_widgets.items():
            if isinstance(widget, ctk.CTkCheckBox):
                self.config.set('ARENA', config_key, 'True' if widget.get() else 'False')
            else:
                self.config.set('ARENA', config_key, widget.get())
                
        for config_key, cb in self.events_widgets.items():
            self.config.set('EVENTS', config_key, 'True' if cb.get() else 'False')
        
        for config_key, widget in self.bounties_widgets.items():
            if isinstance(widget, ctk.CTkCheckBox):
                self.config.set('BOUNTIES', config_key, 'True' if widget.get() else 'False')
            else:
                self.config.set('BOUNTIES', config_key, widget.get())
            
        self.config.save()
        self.destroy()


class ShopWindow(ctk.CTkToplevel):
    """Shop configuration window - original style"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.geometry("430x440")
        self.resizable(False, False)  # Disable window resizing
        self.title('Shop Options')
        self.attributes("-topmost", True)
        
        self.config = parent.config
        self.checkboxes = {}
        
        # Gold Frame
        self.shopGoldFrame = ctk.CTkFrame(master=self, width=200, height=380)
        self.shopGoldFrame.place(x=10, y=10)
        ctk.CTkLabel(master=self.shopGoldFrame, text="Gold Purchases:", font=("Arial", 15, 'bold')).place(x=10, y=5)
        
        # Diamond Frame
        self.shopDiamondFrame = ctk.CTkFrame(master=self, width=200, height=380)
        self.shopDiamondFrame.place(x=220, y=10)
        ctk.CTkLabel(master=self.shopDiamondFrame, text="Diamond Purchases:", font=("Arial", 15, 'bold')).place(x=10, y=5)
        
        gold_items = [
            ('shards_gold', 'Shards', 40),
            ('dust', 'Dust', 70),
            ('silver_emblem', 'Silver Emblems', 100),
            ('gold_emblem', 'Gold Emblems', 130),
            ('poe_coins', 'POE Coins', 160),
        ]
        
        diamond_items = [
            ('timegazer', 'Timegazer Card', 40),
            ('arcanestaffs', 'Arcane Staffs', 70),
            ('baits', 'Baits', 100),
            ('cores', 'Cores', 130),
            ('dust_diamond', 'Dust', 160),
            ('elite_soulstone', 'Elite Soulstone', 190),
            ('rare_soulstone', 'Rare Soulstone', 220),
            ('superb_soulstone', 'Superb Soulstone', 250),
            ('quick', 'Ignore above, do quickbuy', 350),
        ]
        
        for key, text, y in gold_items:
            label = ctk.CTkLabel(master=self.shopGoldFrame, text=text)
            label.place(x=10, y=y)
            checkbox = ctk.CTkCheckBox(master=self.shopGoldFrame, text=None, onvalue=True, offvalue=False)
            checkbox.place(x=165, y=y)
            self.checkboxes[key] = checkbox
            if self.config.getboolean('SHOP', key, fallback=False):
                checkbox.select()
        
        for key, text, y in diamond_items:
            label = ctk.CTkLabel(master=self.shopDiamondFrame, text=text)
            label.place(x=10, y=y)
            checkbox = ctk.CTkCheckBox(master=self.shopDiamondFrame, text=None, onvalue=True, offvalue=False)
            checkbox.place(x=165, y=y)
            self.checkboxes[key] = checkbox
            if self.config.getboolean('SHOP', key, fallback=False):
                checkbox.select()
                
        # Save button
        self.shopSaveButton = ctk.CTkButton(
            master=self,
            text="Save",
            fg_color=["#10B981", "#059669"],
            hover_color=["#059669", "#047857"],
            width=120,
            command=self.shop_save
        )
        self.shopSaveButton.place(x=155, y=400)
        
    def shop_save(self) -> None:
        """Save shop settings"""
        for key, checkbox in self.checkboxes.items():
            self.config.set('SHOP', key, 'True' if checkbox.get() else 'False')
        self.config.save()
        self.destroy()


class AdvancedWindow(ctk.CTkToplevel):
    """Advanced configuration window - original style"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.geometry("350x430")
        self.resizable(False, False)  # Disable window resizing
        self.title('Advanced Options')
        self.attributes("-topmost", True)
        
        self.config = parent.config
        self.entries = {}
        self.checkboxes = {}
        
        self.advancedFrame = ctk.CTkFrame(master=self, width=330, height=370)
        self.advancedFrame.place(x=10, y=10)
        
        ctk.CTkLabel(
            master=self.advancedFrame,
            text="Advanced Options:",
            font=("Arial", 15, 'bold')
        ).place(x=10, y=5)
        
        # Port
        ctk.CTkLabel(master=self.advancedFrame, text='Port:').place(x=10, y=40)
        self.port_entry = ctk.CTkEntry(master=self.advancedFrame, height=25, width=45)
        self.port_entry.insert('end', self.config.get('ADVANCED', 'port', fallback='0'))
        self.port_entry.place(x=275, y=40)
        self.entries['port'] = self.port_entry
        
        # Loading Multiplier
        ctk.CTkLabel(master=self.advancedFrame, text='Delay multiplier:').place(x=10, y=70)
        self.multiplier_entry = ctk.CTkEntry(master=self.advancedFrame, height=25, width=45)
        self.multiplier_entry.insert('end', self.config.get('ADVANCED', 'loadingMuliplier', fallback='1.0'))
        self.multiplier_entry.place(x=275, y=70)
        self.entries['loadingMuliplier'] = self.multiplier_entry
        
        # Victory Check Frequency
        ctk.CTkLabel(master=self.advancedFrame, text='Victory Check Frequency:').place(x=10, y=100)
        self.victory_entry = ctk.CTkEntry(master=self.advancedFrame, height=25, width=45)
        self.victory_entry.insert('end', self.config.get('PUSH', 'victoryCheck', fallback='1'))
        self.victory_entry.place(x=275, y=100)
        self.entries['victoryCheck'] = self.victory_entry
        
        # Suppress victory check spam
        ctk.CTkLabel(master=self.advancedFrame, text='Suppress victory check spam?').place(x=10, y=130)
        self.suppress_cb = ctk.CTkCheckBox(master=self.advancedFrame, text=None, onvalue=True, offvalue=False)
        self.suppress_cb.place(x=295, y=130)
        if self.config.getboolean('PUSH', 'suppressSpam', fallback=False):
            self.suppress_cb.select()
        self.checkboxes['suppressSpam'] = self.suppress_cb
        
        # Use popular formations
        ctk.CTkLabel(master=self.advancedFrame, text='Use popular formations').place(x=10, y=160)
        self.popular_cb = ctk.CTkCheckBox(master=self.advancedFrame, text=None, onvalue=True, offvalue=False)
        self.popular_cb.place(x=295, y=160)
        if self.config.getboolean('ADVANCED', 'popularformations', fallback=False):
            self.popular_cb.select()
        self.checkboxes['popularformations'] = self.popular_cb
        
        # Debug
        ctk.CTkLabel(master=self.advancedFrame, text='Debug Mode').place(x=10, y=190)
        self.debug_cb = ctk.CTkCheckBox(master=self.advancedFrame, text=None, onvalue=True, offvalue=False)
        self.debug_cb.place(x=295, y=190)
        if self.config.getboolean('ADVANCED', 'debug', fallback=False):
            self.debug_cb.select()
        self.checkboxes['debug'] = self.debug_cb
        
        # Emulator path
        ctk.CTkLabel(master=self.advancedFrame, text='Emulator path:').place(x=10, y=220)
        self.emulator_entry = ctk.CTkEntry(master=self.advancedFrame, height=25, width=100)
        self.emulator_entry.insert('end', self.config.get('ADVANCED', 'emulatorpath', fallback=''))
        self.emulator_entry.place(x=220, y=220)
        self.entries['emulatorpath'] = self.emulator_entry
        
        # Save button
        self.saveButton = ctk.CTkButton(
            master=self,
            text="Save",
            fg_color=["#10B981", "#059669"],
            hover_color=["#059669", "#047857"],
            width=120,
            command=self.advanced_save
        )
        self.saveButton.place(x=110, y=390)
        
    def advanced_save(self) -> None:
        """Save advanced settings"""
        for key, entry in self.entries.items():
            if key == 'victoryCheck':
                self.config.set('PUSH', key, entry.get())
            else:
                self.config.set('ADVANCED', key, entry.get())
            
        for key, cb in self.checkboxes.items():
            if key == 'suppressSpam':
                self.config.set('PUSH', key, 'True' if cb.get() else 'False')
            else:
                self.config.set('ADVANCED', key, 'True' if cb.get() else 'False')
            
        self.config.save()
        self.destroy()


class STDOutRedirector:
    """Redirect stdout to textbox with color support (using prefixes)"""
    
    def __init__(self, text_widget):
        self.text_space = text_widget
        
    def write(self, string: str) -> None:
        if not string:
            return
        
        # Handle empty lines (just newline) - no timestamp
        if string == '\n':
            self.text_space.insert('end', '\n')
            self.text_space.see('end')
            return
            
        # Check for color prefixes
        tag = None
        clean_string = string
        
        if string.startswith('ERR'):
            tag = 'error'
            clean_string = string[3:]
        elif string.startswith('WAR'):
            tag = 'warning'
            clean_string = string[3:]
        elif string.startswith('GRE'):
            tag = 'green'
            clean_string = string[3:]
        elif string.startswith('BLU'):
            tag = 'blue'
            clean_string = string[3:]
        elif string.startswith('PUR'):
            tag = 'purple'
            clean_string = string[3:]
        # Fallback for messages without prefix
        else:
            # Default to white/no color
            tag = None
            
        timestamp = '[' + datetime.datetime.now().strftime("%H:%M:%S") + '] '
        
        if tag:
            self.text_space.insert('end', timestamp + clean_string, tag)
        else:
            self.text_space.insert('end', timestamp + clean_string)
            
        self.text_space.see('end')
        
    def flush(self) -> None:
        pass


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description=f'AutoAFK {VERSION}')
    parser.add_argument('-c', '--config', 
                       default='settings.ini',
                       help='Path to configuration file (default: settings.ini)')
    parser.add_argument('-d', '--dailies', 
                       action='store_true',
                       help='Run dailies without GUI')
    parser.add_argument('-at', '--autotower',
                       action='store_true',
                       help='Run Auto-Towers function (push all towers)')
    parser.add_argument('-t', '--tower',
                       type=str,
                       help='Select a specific tower to push (kt, lb, m, w, gb, c, h)')
    parser.add_argument('-sr', '--shadowrealm',
                       action='store_true',
                       help='Run Shadow Realm without GUI (for scheduling)')
    parser.add_argument('-l', '--logging', 
                       action='store_true',
                       help='Enable file logging')
    return parser.parse_args()


def attach_console() -> None:
    """Show headless output in the terminal that started AutoAFK.exe.

    AutoAFK.exe is a window app, so Windows gives it no console and print/log
    output goes nowhere. Attach to the parent's console (PowerShell/cmd) if
    there is one; does nothing when started by Task Scheduler or double-click.
    """
    if sys.platform != 'win32' or sys.stdout is not None:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if not kernel32.AttachConsole(-1):   # ATTACH_PARENT_PROCESS
            return
        kernel32.SetConsoleOutputCP(65001)   # UTF-8, for the symbols in the log
        out = open('CONOUT$', 'w', encoding='utf-8', errors='replace', buffering=1)
        sys.stdout = sys.stderr = out
        # Colours: turn on ANSI escape codes for this console
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        os.environ['AUTOAFK_CONSOLE_COLOURS'] = '1'
        print()   # start below the PowerShell prompt
    except Exception:
        pass


def main() -> None:
    """Main entry point"""
    global args
    args = parse_arguments()

    if args.dailies or args.shadowrealm or args.tower or args.autotower:
        attach_console()
        # Scheduled runs share one emulator: wait for any other run to finish first
        if not wait_for_other_runs():
            return
    
    # If --dailies flag, run headless
    if args.dailies:
        run_dailies_headless()
    elif args.shadowrealm:
        run_shadow_realm_headless()
    # If --tower or --autotower flag, run tower push
    elif args.tower or args.autotower:
        run_tower_push_headless()
    else:
        # Run GUI
        app = App()
        app.mainloop()


_run_lock = None


def wait_for_other_runs(max_wait_hours: float = 4) -> bool:
    """Take the run lock, waiting while another headless run (e.g. Shadow Realm while the
    dailies start) is still going. Two runs at once would fight over the emulator, and each
    shuts down ADB when it finishes. The lock is released automatically when the process ends."""
    global _run_lock
    path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), '.autoafk_run.lock')
    try:
        _run_lock = open(path, 'a+')
    except OSError:
        return True   # can't create the file: just run
    def try_lock() -> bool:
        try:
            if os.name == 'nt':
                import msvcrt
                _run_lock.seek(0)
                msvcrt.locking(_run_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(_run_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if try_lock():
        return True
    print("[INFO] Another AutoAFK run is still going, waiting for it to finish...")
    end = time.time() + max_wait_hours * 3600
    while time.time() < end:
        time.sleep(30)
        if try_lock():
            print("[INFO] Other run finished, starting")
            return True
    print("[ERROR] The other run is still going after hours, skipping this one")
    return False


def run_dailies_headless() -> None:
    """Run dailies without GUI"""
    print(f"AutoAFK {VERSION} - Headless Mode")
    print(f"https://github.com/{GITHUB_REPO}")
    print()
    
    try:
        # Load config
        config = Config(args.config if args.config else 'settings.ini')
        
        # Initialize Logger (this sets up all handlers including custom levels)
        from src.utils.logger import Logger
        Logger()  # Initialize logger singleton
        
        # Initialize components
        print("[INFO] Initializing...")
        notification_manager = NotificationManager(config)
        
        # Enable notifications for all log messages BEFORE initializing device
        from src.utils.logger import add_notification_handler
        add_notification_handler(notification_manager)
        
        # Initialize core modules
        device_manager, image_recognition, game_controller = initialize_core_modules(config)
        if not device_manager:
            print("[ERROR] Failed to connect to device")
            return
        
        # Initialize activity manager
        activity_manager = ActivityManager(
            device_manager, image_recognition, game_controller,
            config, notification_manager
        )
        
        print("[INFO] Starting dailies...")
        
        # Execute dailies using shared function
        execute_dailies(activity_manager, None, None)
            
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup ADB processes
        if 'device_manager' in locals() and device_manager:
            print()  # Empty line without timestamp
            print("[INFO] Cleaning up ADB processes...")
            device_manager.disconnect()
            device_manager._kill_adb_processes()


def run_shadow_realm_headless() -> None:
    """Run Shadow Realm without GUI (e.g. from Task Scheduler)"""
    print(f"AutoAFK {VERSION} - Shadow Realm")
    print(f"https://github.com/{GITHUB_REPO}")
    print()
    device_manager = None
    try:
        config = Config(args.config if args.config else 'settings.ini')
        from src.utils.logger import Logger, add_notification_handler
        Logger()
        notification_manager = NotificationManager(config)
        add_notification_handler(notification_manager)
        device_manager, image_recognition, game_controller = initialize_core_modules(config)
        if not device_manager:
            print("[ERROR] Failed to connect to device")
            return
        activity_manager = ActivityManager(
            device_manager, image_recognition, game_controller,
            config, notification_manager
        )
        game_controller.expand_menus()
        game_controller.wait_until_game_active()
        activity_manager.shadow.run()
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if device_manager:
            print()
            print("[INFO] Cleaning up ADB processes...")
            device_manager.disconnect()
            device_manager._kill_adb_processes()


def run_tower_push_headless() -> None:
    """Run tower push without GUI"""
    print(f"AutoAFK {VERSION} - Tower Push Mode")
    print(f"https://github.com/{GITHUB_REPO}")
    print()
    
    try:
        # Load config
        config = Config(args.config if args.config else 'settings.ini')
        
        # Initialize Logger (this sets up all handlers including custom levels)
        from src.utils.logger import Logger
        Logger()  # Initialize logger singleton
        
        # Initialize components
        print("[INFO] Initializing...")
        notification_manager = NotificationManager(config)
        
        # Enable notifications for all log messages BEFORE initializing device
        from src.utils.logger import add_notification_handler
        add_notification_handler(notification_manager)
        
        # Initialize core modules
        device_manager, image_recognition, game_controller = initialize_core_modules(config)
        if not device_manager:
            print("[ERROR] Failed to connect to device")
            return
        
        # Initialize tower pusher
        pusher = TowerPusher(device_manager, image_recognition, game_controller,
                            config, notification_manager)
        
        # Get push settings
        formation = int(str(config.get('PUSH', 'formation', fallback='3'))[0:1])
        duration = config.getint('PUSH', 'victoryCheck', fallback=1)
        
        print(f"[INFO] Formation: {formation}, Victory Check: {duration} minutes")
        
        # Auto-tower mode (push all towers)
        if args.autotower:
            print("[INFO] Starting Auto-Towers (all towers)...")
            towers = [
                "King's Tower",
                "Lightbearer Tower", 
                "Mauler Tower",
                "Wilder Tower",
                "Graveborn Tower",
                "Celestial Tower",
                "Hypogean Tower"
            ]
            
            for tower in towers:
                print(f"\n[INFO] Pushing {tower}...")
                pusher.push_tower(tower, formation, duration)
                
        # Single tower mode
        elif args.tower:
            # Map short names to full names
            tower_map = {
                'kt': "King's Tower",
                'lb': 'Lightbearer Tower',
                'm': 'Mauler Tower',
                'w': 'Wilder Tower',
                'gb': 'Graveborn Tower',
                'c': 'Celestial Tower',
                'h': 'Hypogean Tower'
            }
            
            tower_name = tower_map.get(args.tower.lower(), args.tower)
            print(f"[INFO] Pushing {tower_name}...")
            pusher.push_tower(tower_name, formation, duration)
            
    except KeyboardInterrupt:
        print("\n[INFO] Tower push stopped by user")
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup ADB processes
        if 'device_manager' in locals() and device_manager:
            print()  # Empty line without timestamp
            print("[INFO] Cleaning up ADB processes...")
            device_manager.disconnect()
            device_manager._kill_adb_processes()


if __name__ == '__main__':
    main()


