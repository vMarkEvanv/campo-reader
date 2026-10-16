"""Native, non-blocking update dialog for the Windows desktop shell."""
import base64
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from PySide6.QtCore import QObject,Signal,QTimer,Slot
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPlainTextEdit,QPushButton,QProgressBar,QCheckBox,QMessageBox,QApplication
import updater
from version import VERSION

class Worker(QObject):
 result=Signal(object)
 failed=Signal(str)
 progress=Signal(int)
 finished=Signal()
 def __init__(self,fn):
  super().__init__();self.fn=fn;self.cancel=threading.Event();self.exiting=False;self.thread=threading.Thread(target=self.run,daemon=True)
 def start(self):self.thread.start()
 def wait(self,milliseconds):self.thread.join(milliseconds/1000)
 def run(self):
  try:
   value=self.fn(self.cancel,lambda n,total:self.progress.emit(int(n*100/total)) if not self.exiting else None)
   if not self.exiting:self.result.emit(value)
  except updater.Cancelled:
   if not self.exiting:self.failed.emit('操作已取消。')
  except updater.UpdateError as exc:
   if not self.exiting:self.failed.emit(str(exc))
  except Exception:
   if not self.exiting:self.failed.emit('更新未完成，请稍后重试。')
  finally:
   if not self.exiting:self.finished.emit()

class UpdateDialog(QDialog):
 def __init__(self,controller):
  super().__init__(controller.window);self.controller=controller;self.setWindowTitle('Campo Reader · 软件更新');self.setMinimumWidth(480)
  self.setStyleSheet('QDialog{background:#162028;color:#e5edf2}QLabel,QCheckBox{color:#dbe7ef}QPushButton{padding:9px 16px;border-radius:8px;background:#a8c8eb;color:#142838}QPushButton:disabled{background:#34434e;color:#8396a4}QPlainTextEdit{background:#10181e;color:#c7d6e1;border:1px solid #33434f;padding:8px}QProgressBar{border:1px solid #33434f;border-radius:5px;text-align:center;color:#dbe7ef}QProgressBar::chunk{background:#80addb}')
  box=QVBoxLayout(self);box.setSpacing(14)
  box.addWidget(QLabel('当前版本 '+VERSION));self.status=QLabel('检查是否有新版本。');self.status.setWordWrap(True);box.addWidget(self.status)
  self.notes=QPlainTextEdit();self.notes.setReadOnly(True);self.notes.setMaximumHeight(140);self.notes.hide();box.addWidget(self.notes)
  self.bar=QProgressBar();self.bar.hide();box.addWidget(self.bar)
  self.auto=QCheckBox('启动时自动检查更新（每天一次）');self.auto.setChecked(controller.settings['auto_check']);self.auto.toggled.connect(controller.set_auto);box.addWidget(self.auto)
  hint=QLabel('更新直接来自 GitHub Releases，无需连接 Tailscale。升级保留账号、课程分类及证明文件。');hint.setWordWrap(True);box.addWidget(hint)
  row=QHBoxLayout();self.check=QPushButton('检查更新');self.check.clicked.connect(lambda:controller.check());row.addWidget(self.check)
  self.install=QPushButton('下载并安装');self.install.setEnabled(False);self.install.clicked.connect(controller.download);row.addWidget(self.install)
  self.cancel_button=QPushButton('取消下载');self.cancel_button.clicked.connect(controller.cancel_download);self.cancel_button.hide();row.addWidget(self.cancel_button)
  self.close_button=QPushButton('稍后');self.close_button.clicked.connect(self.close);row.addWidget(self.close_button);box.addLayout(row)
 def closeEvent(self,event):
  self.controller.cancel_download();event.accept()

class UpdateController(QObject):
 def __init__(self,app,window,root,resource_root,is_syncing=lambda:False):
  super().__init__(window);self.app=app;self.window=window;self.root=Path(root);self.resource_root=Path(resource_root);self.is_syncing=is_syncing
  self.settings=updater.load_settings(root);self.payload=None;self.dialog=None;self.workers=set();self.current=None;self.downloading=False;self.closing=False
  self.key=base64.b64decode((self.resource_root/'update-public-key.txt').read_text().strip(),validate=True)
  if len(self.key)!=32:raise updater.UpdateError('更新公钥不正确。')
 def show(self,check=True):
  if self.dialog is None:self.dialog=UpdateDialog(self)
  self.dialog.show();self.dialog.raise_();self.dialog.activateWindow()
  if check and not self.current:self.check()
 def set_auto(self,value):
  self.settings['auto_check']=bool(value)
  try:updater.save_settings(self.root,self.settings)
  except OSError:
   if self.dialog:self.dialog.status.setText('无法保存更新偏好，请检查本机磁盘。')
 def auto_check(self):
  if self.settings['auto_check'] and time.time()-self.settings['last_attempt']>=86400:self.check(silent=True)
 def work(self,fn,success,failure):
  worker=Worker(fn);self.current=worker;self.workers.add(worker)
  worker.success=success;worker.failure=failure
  worker.result.connect(self.on_result);worker.failed.connect(self.on_failure)
  if self.dialog:worker.progress.connect(self.dialog.bar.setValue)
  worker.finished.connect(self.on_finished);worker.start()
 @Slot(object)
 def on_result(self,value):
  worker=self.sender();self.current=None
  if not self.closing:worker.success(value)
 @Slot(str)
 def on_failure(self,message):
  worker=self.sender();self.current=None
  if not self.closing:worker.failure(message)
 @Slot()
 def on_finished(self):
  worker=self.sender();self.workers.discard(worker);worker.deleteLater()
 def check(self,silent=False):
  if self.current or self.closing:return
  if not silent and self.dialog is None:self.show(check=False)
  self.settings['last_attempt']=time.time()
  try:updater.save_settings(self.root,self.settings)
  except OSError:pass
  if self.dialog:self.dialog.status.setText('正在检查更新…');self.dialog.check.setEnabled(False);self.dialog.install.setEnabled(False)
  self.payload=None
  def success(payload):
   self.payload=payload
   if payload and silent:self.show(check=False)
   if self.dialog:
    self.dialog.check.setEnabled(True);self.dialog.install.setEnabled(bool(payload));self.dialog.status.setText('发现新版本 '+payload['version'] if payload else '当前已是最新版本。')
    self.dialog.notes.setPlainText(payload.get('notes','') if payload else '');self.dialog.notes.setVisible(bool(payload))
  def failure(message):
   if self.dialog:self.dialog.check.setEnabled(True);self.dialog.status.setText(message)
  self.work(lambda event,progress:updater.check_update(self.key,VERSION,event),success,failure)
 def cancel_download(self):
  if self.current:self.current.cancel.set()
 def download(self):
  if self.current or not self.payload:return
  d=self.dialog;d.bar.setValue(0);d.bar.show();d.cancel_button.show();d.check.setEnabled(False);d.install.setEnabled(False);d.status.setText('正在下载更新，请保持网络连接…');self.downloading=True
  payload=dict(self.payload)
  def finish_controls():
   self.downloading=False;d.cancel_button.hide();d.check.setEnabled(True);d.install.setEnabled(True)
  def success(path):
   finish_controls();d.bar.setValue(100);d.status.setText('下载及校验完成。')
   text='将关闭当前程序并安装 '+payload['version']+'，安装后自动重新打开。账号、课程分类和证明文件会保留。'
   if self.is_syncing():text+='\n当前同步尚未结束；建议选择稍后，等同步完成后再更新。'
   if QMessageBox.question(d,'安装更新',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
   if not getattr(sys,'frozen',False):d.status.setText('开发运行模式不执行安装，请使用打包后的 Windows 程序。');return
   asset=payload['installer'];target=Path(sys.executable).resolve().parent
   args=[sys.executable,'--apply-update',str(path),'--sha256',asset['sha256'],'--size',str(asset['size']),'--wait-pid',str(os.getpid()),'--target-dir',str(target)]
   try:subprocess.Popen(args,env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1'),close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
   except OSError:d.status.setText('无法启动安装程序，当前版本可继续使用。');return
   self.app.quit()
  def failure(message):finish_controls();d.status.setText(message)
  self.work(lambda event,progress:updater.download_update(payload,self.root,event,progress),success,failure)
 def shutdown(self):
  self.closing=True
  for worker in list(self.workers):worker.exiting=True;worker.cancel.set()
  for worker in list(self.workers):worker.wait(200)
