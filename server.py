"""Private loopback server for the desktop window. Never binds the LAN."""
import hmac
import json
import secrets
import threading
from http.cookies import SimpleCookie,CookieError
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,quote
from campo_backend.campo import Campo
from campo_backend.console import ConsoleError

ASSETS={
 '/tools/campo-reader':('campo-reader.html','text/html; charset=utf-8'),
 '/tools/campo-reader/':('campo-reader.html','text/html; charset=utf-8'),
 '/campo-reader.js':('campo-reader.js','text/javascript; charset=utf-8'),
 '/campo-workspace.js':('campo-workspace.js','text/javascript; charset=utf-8'),
 '/campo-reader.css':('campo-reader.css','text/css; charset=utf-8'),
 '/work-theme.css':('work-theme.css','text/css; charset=utf-8'),
 '/campo-icon.svg':('campo-icon.svg','image/svg+xml')}

class Handler(BaseHTTPRequestHandler):
 server_version='CampoReaderDesktop'
 def log_message(self,*args):pass
 def reply(self,status,body,kind='application/json; charset=utf-8',headers=None):
  raw=json.dumps(body,ensure_ascii=False).encode() if isinstance(body,dict) else body
  self.send_response(status)
  for k,v in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",**(headers or {})}.items():self.send_header(k,v)
  self.end_headers();self.wfile.write(raw)
 def validate(self,write=False):
  if self.headers.get('Host')!=self.server.address:raise ConsoleError('此接口仅供本机应用使用。',403)
  if self.headers.get('Sec-Fetch-Site')=='cross-site':raise ConsoleError('请求来源不正确。',403)
  origin=self.headers.get('Origin')
  if (write and not origin) or (origin and origin!=self.server.origin):raise ConsoleError('请求来源不正确。',403)
  cookie=SimpleCookie()
  try:cookie.load(self.headers.get('Cookie',''))
  except CookieError:raise ConsoleError('请重新打开应用。',403)
  item=cookie.get(self.server.cookie_name)
  if not item or not hmac.compare_digest(item.value,self.server.secret):raise ConsoleError('请通过桌面程序访问。',403)
  if write and not hmac.compare_digest(self.headers.get('X-Console-CSRF',''),self.server.campo.csrf):raise ConsoleError('页面已失效，请重新打开应用。',403)
 def do_GET(self):
  try:
   parts=urlsplit(self.path)
   if parts.path=='/launch':
    token=parse_qs(parts.query).get('token',[''])[0]
    if self.headers.get('Host')!=self.server.address or not hmac.compare_digest(token,self.server.secret):raise ConsoleError('启动验证失败。',403)
    self.reply(302,b'',headers={'Location':'/tools/campo-reader','Set-Cookie':self.server.cookie_name+'='+self.server.secret+'; Path=/; HttpOnly; SameSite=Strict'})
    return
   self.validate()
   if parts.path in ('/','/favicon.ico'):
    self.reply(302,b'',headers={'Location':'/tools/campo-reader' if parts.path=='/' else '/campo-icon.svg'});return
   if parts.path in ASSETS:
    name,kind=ASSETS[parts.path];self.reply(200,(self.server.public/name).read_bytes(),kind);return
   query=parse_qs(parts.query);account=query.get('id',[None])[0];campo=self.server.campo
   if parts.path=='/api/campo':
    self.reply(200,dict(campo.snapshot(campo.public_user,account),csrf=campo.csrf));return
   if parts.path=='/api/campo/document':
    title,content=campo.document(campo.public_user,account,query.get('document_id',[''])[0])
    self.reply(200,content,'application/pdf',{'Content-Disposition':"attachment; filename=campo-document.pdf; filename*=UTF-8''"+quote(title+'.pdf',safe='')});return
   raise ConsoleError('接口不存在。',404)
  except ConsoleError as exc:self.reply(exc.status,{'error':str(exc)})
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception:self.reply(503,{'error':'本地数据暂不可用，请重新启动应用。'})
 def do_POST(self):
  try:
   self.validate(write=True);parts=urlsplit(self.path)
   if parts.path=='/api/desktop/open-data':
    if self.server.open_data:self.server.open_data()
    self.reply(200,{'ok':True});return
   if parts.path!='/api/campo':raise ConsoleError('接口不存在。',404)
   if not self.headers.get('Content-Type','').startswith('application/json'):raise ConsoleError('请使用 JSON 提交。',415)
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=15*1024*1024:
    self.close_connection=True;raise ConsoleError('请求大小不正确。',413)
   self.connection.settimeout(50);body=json.loads(self.rfile.read(length))
   if not isinstance(body,dict):raise ConsoleError('请求格式不正确。')
   campo=self.server.campo;result=campo.action(campo.public_user,body)
   self.reply(200,dict(result,csrf=campo.csrf))
  except ConsoleError as exc:self.reply(exc.status,{'error':str(exc)})
  except (ValueError,TypeError,KeyError):self.reply(400,{'error':'请求格式不正确。'})
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception:self.reply(503,{'error':'操作未完成，现有数据保留。请稍后重试。'})

class DesktopServer(ThreadingHTTPServer):
 daemon_threads=True
 allow_reuse_address=False
 def __init__(self,data_root,public,open_data=None):
  super().__init__(('127.0.0.1',0),Handler)
  self.public=Path(public);self.campo=Campo(data_root);self.open_data=open_data
  self.secret=secrets.token_urlsafe(32);self.cookie_name='campo_'+secrets.token_hex(8)
  self.address='127.0.0.1:'+str(self.server_address[1]);self.origin='http://'+self.address
  self.launch_url=self.origin+'/launch?token='+self.secret
  self.stop_event=threading.Event()
 def start(self):
  self.http_thread=threading.Thread(target=self.serve_forever,daemon=True);self.http_thread.start()
  self.sync_thread=threading.Thread(target=self.campo.worker,args=(self.stop_event,),daemon=True);self.sync_thread.start()
 def close(self):
  self.stop_event.set();self.shutdown();self.server_close();self.http_thread.join(timeout=3);self.sync_thread.join(timeout=3)
