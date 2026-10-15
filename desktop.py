"""Campo Reader Windows desktop entry point (no shell, no device console)."""
import json
import os
import sys
import tempfile
from pathlib import Path

VERSION='1.0.0'
def resources():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
def data_directory():
 path=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'CampoReader'
 path.mkdir(parents=True,exist_ok=True);return path

def self_test(report_path):
 """Run on the actual Windows bundle, including the bundled browser and Qt window."""
 result={'version':VERSION,'platform':sys.platform}
 try:
  import http.client
  from server import DesktopServer
  from campo_backend.browser import launch_browser
  from playwright.sync_api import sync_playwright
  with tempfile.TemporaryDirectory(prefix='campo-smoke-') as temp:
   srv=DesktopServer(Path(temp),resources()/'public');srv.start()
   try:
    c=http.client.HTTPConnection(srv.address);c.request('GET','/launch?token='+srv.secret);r=c.getresponse();cookie=r.getheader('Set-Cookie').split(';')[0];r.read();c.close()
    c=http.client.HTTPConnection(srv.address);c.request('GET','/api/campo',headers={'Cookie':cookie});r=c.getresponse();assert r.status==200;assert json.loads(r.read())['accounts']==[];c.close();result['loopback_api']=True
    with sync_playwright() as pw:
     browser=launch_browser(pw);page=browser.new_page();page.set_content('<title>Campo test</title>');assert page.title()=='Campo test';browser.close();result['bundled_chromium']=True
    from PySide6.QtCore import QTimer,QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView
    app=QApplication.instance() or QApplication([]);view=QWebEngineView()
    def loaded(ok):
     result['desktop_page_loaded']=bool(ok);QTimer.singleShot(100,app.quit)
    view.loadFinished.connect(loaded);view.resize(1280,850);view.show();view.load(QUrl(srv.launch_url));QTimer.singleShot(25000,app.quit);app.exec();view.close()
    assert result.get('desktop_page_loaded'),'Desktop page did not load'
   finally:srv.close()
  result['ok']=True
 except Exception as exc:result.update(ok=False,error_type=type(exc).__name__)
 Path(report_path).write_text(json.dumps(result,indent=2),encoding='utf-8')
 return 0 if result.get('ok') else 1

def main():
 from campo_backend.browser import configure_browser
 configure_browser()
 if len(sys.argv)>2 and sys.argv[1]=='--self-test':return self_test(sys.argv[2])
 from PySide6.QtCore import QLockFile,QObject,Signal,QUrl,Qt,QTimer
 from PySide6.QtGui import QDesktopServices,QIcon,QAction
 from PySide6.QtWidgets import QApplication,QMainWindow,QFileDialog,QMessageBox
 from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
 from PySide6.QtWebEngineWidgets import QWebEngineView
 from server import DesktopServer
 app=QApplication(sys.argv);app.setApplicationName('Campo Reader');app.setApplicationVersion(VERSION);app.setOrganizationName('CampoReader')
 root=data_directory();lock=QLockFile(str(root/'app.lock'));lock.setStaleLockTime(0)
 if not lock.tryLock(100):
  QMessageBox.information(None,'Campo Reader','程序已经运行，请查看任务栏中的 Campo Reader 窗口。');return 0
 class Bridge(QObject):open_data=Signal()
 bridge=Bridge();bridge.open_data.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))))
 srv=DesktopServer(root,resources()/'public',bridge.open_data.emit);srv.start()
 class Page(QWebEnginePage):
  def acceptNavigationRequest(self,url,kind,is_main):
   value=url.toString()
   if value.startswith(srv.origin+'/') or value.startswith('blob:'+srv.origin+'/') or value=='about:blank':return True
   if url.scheme() in ('https','mailto'):
    QDesktopServices.openUrl(url)
    if getattr(self,'is_popup',False):QTimer.singleShot(0,self.parent().close)
   return False
  def createWindow(self,kind):
   popup=QWebEngineView();popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);page=Page(self.profile(),popup);page.is_popup=True;popup.setPage(page);popup.resize(1000,780);popup.show();window.popups.append(popup);return page
 profile=QWebEngineProfile(app) # off-the-record: no persistent web cookies or browser history
 window=QMainWindow();window.popups=[];window.setWindowTitle('Campo Reader');window.resize(1420,940);window.setMinimumSize(860,640)
 icon=QIcon(str(resources()/'public/campo-icon.svg'));app.setWindowIcon(icon);window.setWindowIcon(icon)
 view=QWebEngineView();page=Page(profile,view);view.setPage(page);window.setCentralWidget(view)
 def download(request):
  url=request.url().toString()
  if not(url.startswith(srv.origin+'/') or url.startswith('blob:'+srv.origin+'/')):request.cancel();return
  filename=request.suggestedFileName() or 'Campo-document.pdf'
  path,_=QFileDialog.getSaveFileName(window,'保存证明 PDF',str(Path.home()/'Downloads'/filename),'PDF 文件 (*.pdf);;所有文件 (*)')
  if not path:request.cancel();return
  request.setDownloadDirectory(str(Path(path).parent));request.setDownloadFileName(Path(path).name);request.accept()
 profile.downloadRequested.connect(download)
 menu=window.menuBar().addMenu('应用')
 def action(label,fn,shortcut=None):
  a=QAction(label,window);a.triggered.connect(fn)
  if shortcut:a.setShortcut(shortcut)
  menu.addAction(a)
 action('重新加载',view.reload,'Ctrl+R');action('打开本地数据文件夹',bridge.open_data.emit)
 action('关于',lambda:QMessageBox.information(window,'关于 Campo Reader','Campo Reader '+VERSION+'\n独立 Windows 桌面版\n数据保存在本机；与 Orange Pi 版本相互独立。\n关闭应用后，本机自动同步随之停止。\n第三方许可见安装目录 THIRD_PARTY_NOTICES.md。'))
 action('退出',window.close,'Ctrl+Q')
 app.aboutToQuit.connect(srv.close);view.load(QUrl(srv.launch_url));window.show()
 code=app.exec();view.setPage(QWebEnginePage(view));page.deleteLater();lock.unlock();return code

if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as exc:
  # No exception text, paths with tokens, request bodies or user data in logs.
  try:
   folder=data_directory();(folder/'startup-error.txt').write_text(type(exc).__name__,encoding='utf-8')
   import ctypes
   if sys.platform=='win32':ctypes.windll.user32.MessageBoxW(None,'启动失败。请重新安装；你的本地数据会保留。','Campo Reader',16)
  finally:raise SystemExit(1)
