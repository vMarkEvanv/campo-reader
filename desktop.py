"""Campo Reader desktop: local Python backend + Microsoft WebView2. No Qt."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from version import VERSION

def resources():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
def data_directory():
 path=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'CampoReader'
 path.mkdir(parents=True,exist_ok=True);return path

def attach_navigation(window,origin):
 from desktop_runtime import local_navigation
 import webbrowser
 def ready():
  control=window.native.webview
  def navigate(sender,args):
   url=str(args.Uri)
   if not local_navigation(url,origin):
    args.Cancel=True
    if url.startswith('https://'):webbrowser.open(url)
  control.NavigationStarting+=navigate
  # Keep the Python delegate alive for the native control's entire lifetime.
  window._campo_navigation=navigate
 window.events.before_show+=ready

def run_window(root,report=None):
 import webview
 from server import DesktopServer
 from desktop_runtime import DesktopLock,open_data,message,ensure_webview2
 from desktop_updates import UpdateController
 from webview.menu import Menu,MenuAction,MenuSeparator
 if sys.platform!='win32':raise RuntimeError('The desktop shell requires Windows WebView2')
 if not ensure_webview2(resources()):
  message('需要 Microsoft Edge WebView2 Runtime。请重新运行 Campo Reader 安装包，联网完成运行时安装。');return 2
 lock=DesktopLock(root)
 if not lock.acquire():message('Campo Reader 已在运行，请查看任务栏。');return 0
 result={'version':VERSION,'platform':sys.platform,'renderer':'edgechromium','ok':False};srv=None;updates=None
 try:
  window=None
  def show_updates():
   if window:window.evaluate_js("window.dispatchEvent(new Event('campo-update-open'))")
  srv=DesktopServer(root,resources()/'public',lambda:open_data(root),show_updates)
  window=webview.create_window('Campo Reader',srv.launch_url,width=1420,height=940,min_size=(860,640),background_color='#101315',text_select=True,zoomable=True)
  updates=UpdateController(root,resources(),notify=show_updates,quit_app=window.destroy,is_syncing=lambda:any(j.get('running') for j in srv.campo.jobs.values()))
  srv.updates=updates;attach_navigation(window,srv.origin)
  webview.settings.update(ALLOW_DOWNLOADS=True,ALLOW_FILE_URLS=False,OPEN_EXTERNAL_LINKS_IN_BROWSER=True,OPEN_DEVTOOLS_IN_DEBUG=False)
  srv.start()
  def about():message('Campo Reader '+VERSION+'\nMicrosoft WebView2 桌面版\n数据保存在本机，与 Orange Pi 版本独立。\n关闭程序后本机自动同步停止。')
  menu=[Menu('应用',[MenuAction('重新加载',lambda:window.load_url(srv.origin+'/tools/campo-reader')),MenuAction('软件更新',show_updates),MenuAction('打开本地数据文件夹',lambda:open_data(root)),MenuSeparator(),MenuAction('关于',about),MenuAction('退出',window.destroy)])]
  def background():
   if not window.events.loaded.wait(45):
    if report:result['error_type']='PageLoadTimeout';window.destroy()
    return
   if report:
    try:
     import time
     deadline=time.monotonic()+30
     while time.monotonic()<deadline:
      value=window.evaluate_js("JSON.stringify({ready:document.getElementById('sync')&&!document.getElementById('sync').disabled,loaded:!!document.getElementById('week').children.length,updates:!!document.querySelector('.desktop-update-dialog')})")
      value=json.loads(value)
      if value['loaded'] and value['updates']:break
      time.sleep(.2)
     assert value['loaded'] and value['updates'],'Main page or update UI did not load'
     result.update(desktop_page_loaded=True,update_dialog=True,loopback_api=True)
     # Native select keyboard popup, then close: exercises the formerly problematic path.
     window.evaluate_js("document.getElementById('tab-grades').click();document.getElementById('grade-kind').focus()")
     import ctypes
     ctypes.windll.user32.keybd_event(0x73,0,0,0);ctypes.windll.user32.keybd_event(0x73,0,2,0)
     time.sleep(.3);ctypes.windll.user32.keybd_event(0x1B,0,0,0);ctypes.windll.user32.keybd_event(0x1B,0,2,0)
     result['dropdown_exercised']=bool(window.evaluate_js("!!document.getElementById('grade-kind')"))
     window.evaluate_js("window.dispatchEvent(new Event('campo-update-open'))")
     time.sleep(.3)
     result['update_dialog_opened']=bool(window.evaluate_js("document.querySelector('.desktop-update-dialog').open"))
     from campo_backend.browser import launch_browser
     from playwright.sync_api import sync_playwright
     with sync_playwright() as pw:
      browser=launch_browser(pw);page=browser.new_page();page.set_content('<title>Campo test</title>');assert page.title()=='Campo test';browser.close()
     result['bundled_chromium']=True
     result['ok']=all(result.get(k) for k in ('desktop_page_loaded','update_dialog','dropdown_exercised','update_dialog_opened','bundled_chromium'))
    except Exception as exc:result['error_type']=type(exc).__name__
    finally:window.destroy()
   else:
    threading.Event().wait(5)
    updates.auto_check()
  webview.start(background,gui='edgechromium',private_mode=True,storage_path=str(Path(root)/'webview-cache'),menu=menu,icon=str(resources()/'packaging/campo.ico'))
 finally:
  if updates:updates.shutdown()
  if srv and hasattr(srv,'http_thread'):srv.close()
  lock.release()
  if report:Path(report).write_text(json.dumps(result,indent=2),encoding='utf-8')
 return (0 if result['ok'] else 1) if report else 0

def main():
 from campo_backend.browser import configure_browser
 configure_browser()
 if '--software-rendering' in sys.argv:
  os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')+' --disable-gpu').strip()
 if len(sys.argv)>2 and sys.argv[1]=='--apply-update':
  import argparse
  from updater import apply_update
  parser=argparse.ArgumentParser();parser.add_argument('--apply-update');parser.add_argument('--sha256');parser.add_argument('--size',type=int);parser.add_argument('--wait-pid',type=int);parser.add_argument('--target-dir');args=parser.parse_args()
  apply_update(args.apply_update,args.sha256,args.size,args.wait_pid,args.target_dir,data_directory());return 0
 if len(sys.argv)>2 and sys.argv[1]=='--self-test':
  with tempfile.TemporaryDirectory(prefix='campo-smoke-') as root:return run_window(Path(root),sys.argv[2])
 return run_window(data_directory())

if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as exc:
  try:
   folder=data_directory();(folder/'startup-error.txt').write_text(type(exc).__name__,encoding='utf-8')
   from desktop_runtime import message
   message('启动失败。请重新运行安装包并确认 WebView2 Runtime 已安装；本地数据会保留。')
  finally:raise SystemExit(1)
