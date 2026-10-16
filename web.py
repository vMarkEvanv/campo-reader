"""Standalone single-owner web entry. Shared Campo backend/UI; no BLOG modules."""
import argparse
import os
from pathlib import Path
import signal
import threading
from urllib.parse import urlsplit
from server import DesktopServer,Handler
from campo_backend.console import ConsoleError

class WebHandler(Handler):
 def validate(self,write=False):
  host=self.headers.get('Host','')
  if host not in self.server.allowed_hosts:raise ConsoleError('请求地址未获允许。',403)
  if self.headers.get('Sec-Fetch-Site')=='cross-site':raise ConsoleError('请求来源不正确。',403)
  origin=self.headers.get('Origin')
  if (write and not origin) or (origin and origin not in ('http://'+host,'https://'+host)):raise ConsoleError('请求来源不正确。',403)
  if write:
   import hmac
   if not hmac.compare_digest(self.headers.get('X-Console-CSRF',''),self.server.campo.csrf):raise ConsoleError('页面已失效，请刷新。',403)
 def do_GET(self):
  if urlsplit(self.path).path=='/launch':
   self.reply(404,{'error':'接口不存在。'});return
  super().do_GET()
 def do_POST(self):
  if urlsplit(self.path).path.startswith('/api/desktop/'):
   self.reply(404,{'error':'网页版不提供桌面操作。'});return
  super().do_POST()

class WebServer(DesktopServer):
 def __init__(self,root,public,host='127.0.0.1',port=8090,allowed_hosts=()):
  # Reuse lifecycle and shared API, replacing the local-window authentication.
  super().__init__(root,public)
  self.server_close()
  from http.server import ThreadingHTTPServer
  ThreadingHTTPServer.__init__(self,(host,port),WebHandler)
  actual=self.server_address[1]
  self.allowed_hosts={'127.0.0.1:'+str(actual),'localhost:'+str(actual),*allowed_hosts}
  self.address='127.0.0.1:'+str(actual);self.origin='http://'+self.address
  self.desktop=False

def main():
 p=argparse.ArgumentParser(description='Campo Reader web (single-owner private service)')
 p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8090)
 p.add_argument('--allowed-host',action='append',default=[],help='Exact reverse-proxy Host including port')
 p.add_argument('--data-dir',type=Path,default=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'campo-reader-web')
 a=p.parse_args();a.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
 server=WebServer(a.data_dir,Path(__file__).resolve().parent/'public',a.host,a.port,a.allowed_host)
 stopped=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
 server.start();print('Campo Reader web listening on '+a.host+':'+str(server.server_address[1]),flush=True)
 try:stopped.wait()
 finally:server.close()
if __name__=='__main__':main()
