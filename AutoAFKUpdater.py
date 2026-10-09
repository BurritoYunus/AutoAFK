"""
AutoAFK Updater for Compiled Version
Downloads and installs the latest compiled release from GitHub
"""
import os
import sys
import requests
import zipfile
import shutil
import tempfile
import subprocess
import time
import re
from pathlib import Path

# GitHub Repository - updates come from the BurritoYunus/AutoAFK fork
GITHUB_REPO = "BurritoYunus/AutoAFK"
GITHUB_BRANCH = "master"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_BRANCH_ZIP_URL = f"https://api.github.com/repos/{GITHUB_REPO}/zipball/{GITHUB_BRANCH}"
GITHUB_RAW_MAIN_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/main.py"

# Never overwritten when updating a source install
SOURCE_KEEP = {'settings.ini', 'logs', 'debug', 'venv', '.venv', 'env', '.git', '.idea', '.vscode'}



def print_header():
    """Print updater header"""
    print("=" * 60)
    print("AutoAFK Updater v2.0")
    print("=" * 60)
    print()


def get_latest_release():
    """Get latest release info from GitHub"""
    print("[1/7] Checking for updates...")
    try:
        response = requests.get(GITHUB_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        version = data.get('tag_name', '').lstrip('v')
        download_url = None
        
        # Find the ZIP asset (compiled version)
        for asset in data.get('assets', []):
            if asset['name'].endswith('.zip') and 'AutoAFK' in asset['name']:
                download_url = asset['browser_download_url']
                break
        
        if not download_url:
            print("[ERROR] No compiled ZIP file found in release")
            print("[INFO] Looking for file named 'AutoAFK.zip' or similar")
            return None, None
        
        print(f"[INFO] Latest version: {version}")
        return version, download_url
    except Exception as e:
        print(f"[ERROR] Failed to check for updates: {e}")
        return None, None


def get_latest_source():
    """Latest source code: the latest release's zipball, or the branch if there is no release"""
    print("[1/7] Checking for updates...")
    try:
        response = requests.get(GITHUB_API_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            version = data.get('tag_name', '').lstrip('v')
            print(f"[INFO] Latest release: {version}")
            return version, data.get('zipball_url')

        if response.status_code == 404:
            print(f"[INFO] No releases on {GITHUB_REPO}, using the {GITHUB_BRANCH} branch")
            raw = requests.get(GITHUB_RAW_MAIN_URL, timeout=10)
            raw.raise_for_status()
            match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', raw.text, re.MULTILINE)
            version = match.group(1) if match else GITHUB_BRANCH
            print(f"[INFO] Latest version on {GITHUB_BRANCH}: {version}")
            return version, GITHUB_BRANCH_ZIP_URL

        response.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to check for updates: {e}")
    return None, None


def install_source_update(extract_dir):
    """Copy a downloaded source tree over the current folder, keeping settings and local folders"""
    print("[6/7] Installing update...")
    try:
        # GitHub zipballs contain one top folder named owner-repo-<sha>
        entries = [os.path.join(extract_dir, e) for e in os.listdir(extract_dir)]
        dirs = [e for e in entries if os.path.isdir(e)]
        source_dir = dirs[0] if len(dirs) == 1 and len(entries) == 1 else extract_dir

        if not os.path.exists(os.path.join(source_dir, 'main.py')):
            print(f"[ERROR] main.py not found in the downloaded files")
            return False

        copied = 0
        for item in os.listdir(source_dir):
            if item in SOURCE_KEEP:
                continue
            src = os.path.join(source_dir, item)
            dst = os.path.join(os.getcwd(), item)
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                copied += 1
            except PermissionError:
                if item.startswith('AutoAFKUpdater'):
                    # The running updater can't replace itself; update.bat applies it next time
                    shutil.copy2(src, dst + '.new')
                else:
                    print(f"[WARNING] Could not copy {item} (in use)")
            except Exception as e:
                print(f"[WARNING] Could not copy {item}: {e}")

        print(f"[INFO] Installed {copied} items")

        if os.path.exists('requirements.txt'):
            print("[INFO] Updating Python packages...")
            subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '--quiet'])
        return True
    except Exception as e:
        print(f"[ERROR] Installation failed: {e}")
        return False


def update_git_checkout():
    """Source install that is a git clone: fast-forward it instead of copying files"""
    print("[INFO] Git checkout found, pulling latest changes...")
    try:
        code = subprocess.call(['git', 'pull', '--ff-only'])
        if code != 0:
            print("[ERROR] git pull failed - update the clone manually")
            return False
        if os.path.exists('requirements.txt'):
            subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '--quiet'])
        return True
    except FileNotFoundError:
        print("[ERROR] git is not installed")
        return False


def restart_source_bot():
    """Start main.py again with this Python"""
    print("[7/7] Restarting bot...")
    try:
        if sys.platform == 'win32':
            subprocess.Popen([sys.executable, 'main.py'], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, 'main.py'])
        print("[INFO] Bot restarted!")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to restart bot: {e}")
        return False


def download_update(url, temp_dir):
    """Download update ZIP file"""
    print("[2/7] Downloading update...")
    try:
        zip_path = os.path.join(temp_dir, 'update.zip')
        
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\r[INFO] Downloaded: {percent:.1f}%", end='')
        
        print()
        print(f"[INFO] Downloaded: {os.path.getsize(zip_path) / 1024 / 1024:.1f} MB")
        return zip_path
    except Exception as e:
        print(f"[ERROR] Failed to download: {e}")
        return None


def backup_settings(backup_dir):
    """Backup only settings.ini"""
    print("[3/7] Backing up settings...")
    try:
        if os.path.exists('settings.ini'):
            shutil.copy2('settings.ini', os.path.join(backup_dir, 'settings.ini'))
            print("[INFO] Settings backed up")
        else:
            print("[INFO] No settings.ini found (first run?)")
        return True
    except Exception as e:
        print(f"[ERROR] Backup failed: {e}")
        return False


def extract_update(zip_path, extract_dir):
    """Extract update ZIP"""
    print("[4/7] Extracting update...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        print(f"[INFO] Extracted successfully")
        return True
    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        return False


def close_running_bot(source=False):
    """Try to close running AutoAFK.exe"""
    print("[5/7] Closing running bot...")
    try:
        # In auto mode the UI closes itself, just wait for it
        time.sleep(5)
        if source:
            # main.py closes itself; don't pkill (it would match this updater too)
            print("[INFO] Bot closed")
            return True
        
        # Kill any remaining AutoAFK.exe process as fallback
        if sys.platform == 'win32':
            os.system('taskkill /F /IM AutoAFK.exe >nul 2>&1')
        else:
            os.system('pkill -f AutoAFK')
        
        time.sleep(1)
        print("[INFO] Bot closed")
        return True
    except Exception as e:
        print(f"[WARNING] Could not close bot: {e}")
        return True  # Continue anyway


def install_update(extract_dir, backup_dir):
    """Install extracted update"""
    print("[6/7] Installing update...")
    try:
        # Find the extracted AutoAFK folder
        extracted_folders = [f for f in os.listdir(extract_dir) 
                           if os.path.isdir(os.path.join(extract_dir, f)) and 'AutoAFK' in f]
        
        if extracted_folders:
            source_dir = os.path.join(extract_dir, extracted_folders[0])
        else:
            source_dir = extract_dir
        
        # Check if source has AutoAFK.exe
        if not os.path.exists(os.path.join(source_dir, 'AutoAFK.exe')):
            print(f"[ERROR] AutoAFK.exe not found in extracted files")
            print(f"[INFO] Looking in: {source_dir}")
            return False
        
        # Get current directory
        current_dir = os.getcwd()
        
        # Remove old files (except settings.ini, update.bat, and backup)
        print("[INFO] Removing old files...")
        items_to_remove = []
        for item in os.listdir(current_dir):
            # Skip settings.ini, update.bat, backup folders, and updater files
            if item in ['settings.ini', 'update.bat', 'AutoAFKUpdater.exe', 'AutoAFKUpdater.py', 
                       'settings.ini.backup', 'debug', 'logs', '_internal']:
                continue
            
            item_path = os.path.join(current_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                items_to_remove.append(item)
            except Exception as e:
                print(f"[WARNING] Could not remove {item}: {e}")
        
        print(f"[INFO] Removed {len(items_to_remove)} old items")
        
        # Copy new files
        print("[INFO] Installing new files...")
        copied_count = 0
        for item in os.listdir(source_dir):
            src = os.path.join(source_dir, item)
            dst = os.path.join(current_dir, item)
            
            # Skip settings.ini from new version ONLY if user already has one
            if item == 'settings.ini' and os.path.exists(dst):
                continue
            
            # Special handling for _internal folder (ensure full update)
            if item == '_internal':
                if os.path.exists(dst):
                    print(f"[INFO] Updating _internal contents...")
                    # Copy all files from new _internal to old _internal
                    for subitem in os.listdir(src):
                        s_sub = os.path.join(src, subitem)
                        d_sub = os.path.join(dst, subitem)
                        
                        try:
                            if os.path.isdir(s_sub):
                                if os.path.exists(d_sub):
                                    shutil.rmtree(d_sub)
                                shutil.copytree(s_sub, d_sub)
                            else:
                                # Try to overwrite
                                try:
                                    shutil.copy2(s_sub, d_sub)
                                except PermissionError:
                                    # If file is in use (like the running updater), stage as .new
                                    print(f"[INFO] Staging {subitem} for next run...")
                                    shutil.copy2(s_sub, d_sub + ".new")
                        except Exception as e:
                            print(f"[WARNING] Could not update {subitem}: {e}")
                else:
                    # No existing _internal, just copy
                    shutil.copytree(src, dst)
                
                copied_count += 1
                continue
            
            try:
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                copied_count += 1
            except Exception as e:
                print(f"[WARNING] Could not copy {item}: {e}")
        
        print(f"[INFO] Installed {copied_count} new items")
        
        # Restore settings.ini from backup
        backup_settings_file = os.path.join(backup_dir, 'settings.ini')
        if os.path.exists(backup_settings_file):
            shutil.copy2(backup_settings_file, os.path.join(current_dir, 'settings.ini'))
            print("[INFO] Settings restored")
        
        print("[INFO] Installation complete!")
        return True
    except Exception as e:
        print(f"[ERROR] Installation failed: {e}")
        return False


def restart_bot():
    """Restart AutoAFK.exe"""
    print("[7/7] Restarting bot...")
    try:
        # Check current dir and parent dir
        exe_path = os.path.join(os.getcwd(), 'AutoAFK.exe')
        
        if not os.path.exists(exe_path):
             # Try parent dir (if running from _internal)
             exe_path = os.path.join(os.path.dirname(os.getcwd()), 'AutoAFK.exe')
             
        if not os.path.exists(exe_path):
            print("[ERROR] AutoAFK.exe not found!")
            return False
        
        # Start bot in background
        print(f"[INFO] Starting: {exe_path}")
        if sys.platform == 'win32':
            subprocess.Popen([exe_path], shell=False, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([exe_path])
        
        print("[INFO] Bot restarted!")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to restart bot: {e}")
        print("[INFO] Please start AutoAFK.exe manually")
        return False



def restore_backup(backup_dir):
    """Restore settings from backup"""
    print("[INFO] Restoring settings from backup...")
    try:
        backup_settings = os.path.join(backup_dir, 'settings.ini')
        if os.path.exists(backup_settings):
            shutil.copy2(backup_settings, 'settings.ini')
            print("[INFO] Settings restored")
        return True
    except Exception as e:
        print(f"[ERROR] Restore failed: {e}")
        return False


def prepare_console():
    """Keep the console from freezing the update.

    On Windows, clicking inside a console window with QuickEdit mode on starts a
    text selection and pauses the program until a key is pressed, which looks
    like the updater hanging. Turn QuickEdit off for this window and make sure
    every line is shown right away.
    """
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
    except Exception:
        pass


def main():
    """Main updater function"""
    prepare_console()
    print_header()

    # Parse arguments
    auto_mode = '--auto' in sys.argv
    
    # Determine working directory
    # 1. If we are running as a frozen EXE
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir) == '_internal':
            os.chdir(os.path.dirname(exe_dir))
        else:
            os.chdir(exe_dir)
    # 2. If we are running as a script and in _internal
    elif '_internal' in os.getcwd():
        os.chdir('..')
    
    # Check if we're in the right directory
    if not os.path.exists('AutoAFK.exe') and not os.path.exists('main.py'):
        print("[ERROR] Application not found!")
        print(f"[DEBUG] Current directory: {os.getcwd()}")
        print("[INFO] Please run updater from AutoAFK directory")
        if not auto_mode:
            input("Press Enter to exit...")
        return 1

    if not os.path.exists('AutoAFK.exe'):
        # Running from source (start.bat / python main.py)
        return update_source(auto_mode)

    # Get latest release
    version, download_url = get_latest_release()
    if not version or not download_url:
        if not auto_mode:
            input("Press Enter to exit...")
        return 1
    
    # Confirm update (skip in auto mode)
    if not auto_mode:
        print()
        print(f"Update to version {version}?")
        print("[WARNING] Bot will be closed and restarted")
        response = input("Continue? (y/n): ").lower()
        if response != 'y':
            print("[INFO] Update cancelled")
            return 0
    else:
        print(f"[AUTO] Updating to version {version}...")
    
    print()
    
    # Create temp directories
    temp_dir = tempfile.mkdtemp(prefix='afk_arena_bot_update_')
    backup_dir = tempfile.mkdtemp(prefix='afk_arena_bot_backup_')
    
    try:
        # Backup settings
        if not backup_settings(backup_dir):
            print("[ERROR] Backup failed, aborting update")
            if not auto_mode:
                input("Press Enter to exit...")
            return 1
        
        # Download update
        zip_path = download_update(download_url, temp_dir)
        if not zip_path:
            if not auto_mode:
                input("Press Enter to exit...")
            return 1
        
        # Extract update
        extract_dir = os.path.join(temp_dir, 'extracted')
        os.makedirs(extract_dir, exist_ok=True)
        if not extract_update(zip_path, extract_dir):
            if not auto_mode:
                input("Press Enter to exit...")
            return 1
        
        # Close running bot
        close_running_bot()
        
        # Install update
        if not install_update(extract_dir, backup_dir):
            print("[ERROR] Installation failed, restoring settings...")
            restore_backup(backup_dir)
            if not auto_mode:
                input("Press Enter to exit...")
            return 1
        
        print()
        print("=" * 60)
        print(f"✓ Successfully updated to version {version}!")
        print("=" * 60)
        print()
        
        # Restart bot
        if restart_bot():
            print()
            print("[INFO] Update complete! Bot is starting...")
            time.sleep(5)  # Keep window visible so user can see result
        else:
            print()
            print("[INFO] Please start AutoAFK.exe manually")
            if not auto_mode:
                input("Press Enter to exit...")
            else:
                time.sleep(10)  # Keep window visible on failure
        
    except Exception as e:
        print(f"[ERROR] Update failed: {e}")
        print("[INFO] Restoring settings...")
        restore_backup(backup_dir)
        if not auto_mode:
            input("Press Enter to exit...")
        return 1
    finally:
        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
    
    return 0


def update_source(auto_mode):
    """Update a source install from GitHub"""
    def done(code):
        if not auto_mode:
            input("Press Enter to exit...")
        return code

    if os.path.isdir('.git'):
        close_running_bot(source=True)
        if not update_git_checkout():
            return done(1)
        restart_source_bot()
        return 0

    version, download_url = get_latest_source()
    if not version or not download_url:
        return done(1)

    if not auto_mode:
        print()
        print(f"Update to version {version}?")
        print("[WARNING] Bot will be closed and restarted")
        if input("Continue? (y/n): ").lower() != 'y':
            print("[INFO] Update cancelled")
            return 0
    else:
        print(f"[AUTO] Updating to version {version}...")

    temp_dir = tempfile.mkdtemp(prefix='afk_arena_bot_update_')
    backup_dir = tempfile.mkdtemp(prefix='afk_arena_bot_backup_')
    try:
        if not backup_settings(backup_dir):
            return done(1)
        zip_path = download_update(download_url, temp_dir)
        if not zip_path:
            return done(1)
        extract_dir = os.path.join(temp_dir, 'extracted')
        os.makedirs(extract_dir, exist_ok=True)
        if not extract_update(zip_path, extract_dir):
            return done(1)
        close_running_bot(source=True)
        if not install_source_update(extract_dir):
            restore_backup(backup_dir)
            return done(1)
        print()
        print(f"✓ Successfully updated to version {version}!")
        restart_source_bot()
        time.sleep(5)
        return 0
    except Exception as e:
        print(f"[ERROR] Update failed: {e}")
        restore_backup(backup_dir)
        return done(1)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
