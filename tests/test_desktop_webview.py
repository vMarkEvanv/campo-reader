import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from desktop_runtime import DesktopLock,local_navigation
from desktop_updates import UpdateController
from updater import UpdateError,Cancelled

ROOT=Path(__file__).resolve().parents[1]
class DesktopWebviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.controller=UpdateController(Path(self.tmp.name),ROOT)
  self.addCleanup(self.controller.shutdown)
 def wait(self):
  if self.controller.thread:self.controller.thread.join(3)
  self.assertFalse(self.controller.status()['busy'])
 def test_lock_and_reacquire(self):
  a=DesktopLock(self.tmp.name);b=DesktopLock(self.tmp.name)
  self.assertTrue(a.acquire());self.assertFalse(b.acquire());a.release();self.assertTrue(b.acquire());b.release()
 def test_navigation_does_not_accept_deceptive_local_or_file_urls(self):
  origin='http://127.0.0.1:1234'
  for url in [origin+'/tools/campo-reader','about:blank','blob:'+origin+'/file']:self.assertTrue(local_navigation(url,origin))
  for url in ['http://127.0.0.1:12345/','http://127.0.0.1:1234@evil.test/','file:///tmp/a','https://evil.test/',origin+'.evil.test/']:self.assertFalse(local_navigation(url,origin))
 def test_check_download_progress_and_preferences(self):
  payload={'version':'9.0.0','notes':'hello','installer':{'size':3,'sha256':'0'*64}}
  with patch('desktop_updates.updater.check_update',return_value=payload):self.controller.check();self.wait()
  self.assertEqual(self.controller.status()['available_version'],'9.0.0')
  path=Path(self.tmp.name)/'update.exe'
  def download(payload,root,event,progress):progress(3,3);return path
  with patch('desktop_updates.updater.download_update',side_effect=download):self.controller.download();self.wait()
  self.assertTrue(self.controller.status()['downloaded']);self.assertEqual(self.controller.status()['progress'],100)
  self.controller.action({'action':'preferences','auto_check':False});self.assertFalse(self.controller.status()['auto_check'])
  with self.assertRaises(UpdateError):self.controller.action({'action':'preferences','auto_check':'no'})
  with self.assertRaises(UpdateError):self.controller.install() # Development mode cannot run installers.
 def test_cancel_and_busy_are_nonblocking(self):
  started=threading.Event()
  def check(key,version,event):started.set();event.wait(3);raise Cancelled('cancel')
  with patch('desktop_updates.updater.check_update',side_effect=check) as fn:
   self.controller.check();self.assertTrue(started.wait(1));self.controller.check()
   self.assertEqual(fn.call_count,1);self.controller.action({'action':'cancel'});self.wait()
  self.assertIn('取消',self.controller.status()['message'])
 def test_update_error_has_no_raw_exception_details(self):
  with patch('desktop_updates.updater.check_update',side_effect=RuntimeError('private error')):self.controller.check();self.wait()
  self.assertNotIn('private error',json.dumps(self.controller.status()))
