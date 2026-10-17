"""Run the shared application only on this phone's private loopback interface."""
import json,os
from pathlib import Path
_server=None
_foreground=True

def start(root,public):
    global _server
    os.environ['USER']='campo-mobile';os.environ['LOGNAME']='campo-mobile'
    from server import DesktopServer,ASSETS,Handler
    ASSETS.update({'/android-mobile.css':('android-mobile.css','text/css; charset=utf-8'),'/android-mobile.js':('android-mobile.js','text/javascript; charset=utf-8')})
    class MobileHandler(Handler):
        def do_GET(self):
            from urllib.parse import urlsplit
            if urlsplit(self.path).path=='/api/app':
                try:self.validate();self.reply(200,{'mode':'android','version':'0.1.0'})
                except Exception:self.reply(403,{'error':'请重新打开应用。'})
            else:super().do_GET()
    _server=DesktopServer(Path(root),Path(public));_server.RequestHandlerClass=MobileHandler;_server.desktop=False
    original_tick=_server.campo.tick
    _server.campo.tick=lambda:original_tick() if _foreground else None
    _server.start()
    return json.dumps({'url':_server.launch_url,'origin':_server.origin,'cookie':_server.cookie_name+'='+_server.secret})

def export_document(url):
    from urllib.parse import urlsplit,parse_qs
    u=urlsplit(url)
    if not _server or u.scheme!='http' or u.netloc!=_server.address or u.path!='/api/campo/document':raise ValueError('不是本机归档文件。')
    q=parse_qs(u.query);title,content=_server.campo.document(_server.campo.public_user,q.get('id',[None])[0],q.get('document_id',[''])[0])
    import re
    title=re.sub(r'[^\w .()\-\u4e00-\u9fff]','_',title)[:120] or 'Campo document'
    folder=Path(_server.campo.root).parents[1]/'exports';folder.mkdir(exist_ok=True)
    # Java copies into the private FileProvider cache, never exposes the data directory.
    path=folder/'document.pdf';path.write_bytes(content)
    return json.dumps({'path':str(path),'title':title+'.pdf'})

def diagnostics():
    """Synthetic self-test only: never inspect a real account or access FAU."""
    import tempfile
    from campo_backend.campo import Campo
    with tempfile.TemporaryDirectory() as d:
        c=Campo(d);a=c.action(c.public_user,{'action':'add','label':'Synthetic test'})['account']
        assert c.snapshot(c.public_user,a)['account']==a
        value=c.cipher.encrypt(b'local-test');assert c.cipher.decrypt(value)==b'local-test'
    return True

def foreground(value):
    global _foreground
    _foreground=bool(value)
