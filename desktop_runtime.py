"""Small native platform helpers, independent of Qt and the web renderer."""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

class DesktopLock:
 def __init__(self,root):self.path=Path(root)/'desktop.instance.lock';self.file=None
 def acquire(self):
  self.file=self.path.open('a+b');self.file.seek(0)
  if self.path.stat().st_size==0:self.file.write(b'0');self.file.flush();self.file.seek(0)
  try:
   if sys.platform=='win32':
    import msvcrt
    msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl
    fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
   return True
  except OSError:self.file.close();self.file=None;return False
 def release(self):
  if self.file:self.file.close();self.file=None

def local_navigation(url,origin):
 try:
  p=urlsplit(url);base=urlsplit(origin)
  return url=='about:blank' or (p.scheme==base.scheme and p.netloc==base.netloc and not p.username and not p.password) or url.startswith('blob:'+origin+'/')
 except ValueError:return False

def message(text):
 if sys.platform=='win32':
  import ctypes
  ctypes.windll.user32.MessageBoxW(None,text,'Campo Reader',0x40)

def open_data(root):
 if sys.platform=='win32':os.startfile(str(Path(root).resolve()))

def webview2_installed():
 if sys.platform!='win32':return False
 import winreg
 key=r'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
 for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
  for view in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
   try:
    with winreg.OpenKey(hive,key,0,winreg.KEY_READ|view) as handle:
     version=winreg.QueryValueEx(handle,'pv')[0]
     if version and version!='0.0.0.0':return True
   except OSError:pass
 return False

def ensure_webview2(resource_root):
 if webview2_installed():return True
 if sys.platform!='win32':return False
 import ctypes,subprocess
 answer=ctypes.windll.user32.MessageBoxW(None,'需要安装 Microsoft WebView2 Runtime。是否联网安装？','Campo Reader',0x24)
 bootstrapper=Path(resource_root)/'packaging/MicrosoftEdgeWebview2Setup.exe'
 if answer!=6 or not bootstrapper.is_file():return False
 try:subprocess.run([str(bootstrapper),'/silent','/install'],timeout=240,creationflags=subprocess.CREATE_NO_WINDOW,check=False)
 except (OSError,subprocess.TimeoutExpired):return False
 return webview2_installed()
