"""Thread-safe update controller shared with the desktop's web dialog; no GUI toolkit."""
import base64
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
import updater
from version import VERSION

class UpdateController:
 def __init__(self,root,resource_root,notify=lambda:None,quit_app=lambda:None,is_syncing=lambda:False):
  self.root=Path(root);self.settings=updater.load_settings(root);self.notify=notify;self.quit_app=quit_app;self.is_syncing=is_syncing
  self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None;self.closing=False;self.payload=None;self.path=None
  self.state={'version':VERSION,'busy':False,'operation':'','message':'检查是否有新版本。','progress':None,'available_version':None,'notes':'','downloaded':False}
  self.key=base64.b64decode((Path(resource_root)/'update-public-key.txt').read_text().strip(),validate=True)
  if len(self.key)!=32:raise updater.UpdateError('更新公钥不正确。')
 def status(self):
  with self.lock:return dict(self.state,auto_check=self.settings['auto_check'],syncing=bool(self.is_syncing()))
 def show(self):self.notify()
 def _work(self,operation,fn,done):
  with self.lock:
   if self.state['busy'] or self.closing:return False
   self.cancel=threading.Event();event=self.cancel
   self.state.update(busy=True,operation=operation,progress=None,message='正在检查更新…' if operation=='check' else '正在下载并校验更新…')
   def progress(n,total):
    with self.lock:
     if not self.closing:self.state['progress']=min(100,int(n*100/total)) if total else None
   def run():
    try:
     value=fn(event,progress)
     with self.lock:
      if not self.closing:done(value)
    except updater.Cancelled:
     with self.lock:self.state['message']='操作已取消。'
    except updater.UpdateError as exc:
     with self.lock:self.state['message']=str(exc)
    except Exception:
     with self.lock:self.state['message']='更新未完成，请稍后重试。'
    finally:
     with self.lock:self.state.update(busy=False,operation='')
   self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return True
 def check(self,silent=False):
  with self.lock:
   if self.state['busy'] or self.closing:return
   self.settings['last_attempt']=time.time()
   updater.save_settings(self.root,self.settings)
   self.payload=None;self.path=None;self.state.update(available_version=None,downloaded=False,notes='')
   def done(payload):
    self.payload=payload;self.state.update(available_version=payload['version'] if payload else None,notes=payload.get('notes','') if payload else '',message='发现新版本 '+payload['version'] if payload else '当前已是最新版本。')
    if payload and silent:threading.Thread(target=self.notify,daemon=True).start()
   self._work('check',lambda event,progress:updater.check_update(self.key,VERSION,event),done)
 def auto_check(self):
  with self.lock:due=self.settings['auto_check'] and time.time()-self.settings['last_attempt']>=86400
  if due:self.check(silent=True)
 def download(self):
  with self.lock:
   if not self.payload or self.state['busy']:return
   payload=dict(self.payload)
   def done(path):self.path=path;self.state.update(downloaded=True,progress=100,message='下载及签名校验完成，可安装更新。')
   self._work('download',lambda event,progress:updater.download_update(payload,self.root,event,progress),done)
 def install(self):
  with self.lock:
   if self.state['busy'] or not self.path or not self.payload:raise updater.UpdateError('请先下载并校验更新。')
   if self.is_syncing():raise updater.UpdateError('数据正在同步，请完成后再安装更新。')
   if not getattr(sys,'frozen',False):raise updater.UpdateError('开发运行模式不执行安装。')
   asset=self.payload['installer'];target=Path(sys.executable).resolve().parent
   args=[sys.executable,'--apply-update',str(self.path),'--sha256',asset['sha256'],'--size',str(asset['size']),'--wait-pid',str(os.getpid()),'--target-dir',str(target)]
   subprocess.Popen(args,env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1'),close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
   self.state['message']='正在关闭程序并安装更新…'
   threading.Timer(.3,self.quit_app).start()
 def action(self,payload):
  operation=payload.get('action')
  if operation=='check':self.check()
  elif operation=='download':self.download()
  elif operation=='cancel':self.cancel.set()
  elif operation=='install':self.install()
  elif operation=='preferences':
   value=payload.get('auto_check')
   if type(value) is not bool:raise updater.UpdateError('更新选项不正确。')
   with self.lock:self.settings['auto_check']=value;updater.save_settings(self.root,self.settings)
  else:raise updater.UpdateError('不支持的更新操作。')
  return self.status()
 def shutdown(self):
  with self.lock:self.closing=True;self.cancel.set();thread=self.thread
  if thread and thread is not threading.current_thread():thread.join(timeout=1)
