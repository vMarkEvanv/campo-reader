"""Use the browser included in the Windows application; no downloads at runtime."""
import os
import sys
from pathlib import Path

def configure_browser():
    if getattr(sys,'frozen',False):
        os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path(sys._MEIPASS)/'browsers')

def launch_browser(playwright):
    configure_browser()
    options={'headless':True,'timeout':30000,'args':['--disable-dev-shm-usage']}
    if sys.platform.startswith('linux') and Path('/usr/bin/chromium-browser').exists():options['executable_path']='/usr/bin/chromium-browser'
    return playwright.chromium.launch(**options)
