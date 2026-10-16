import http.client
import json
from pathlib import Path
import tempfile
import unittest
from web import WebServer

class WebTests(unittest.TestCase):
 def test_standalone_shared_api_csrf_and_scope(self):
  with tempfile.TemporaryDirectory() as root:
   server=WebServer(Path(root),Path(__file__).resolve().parents[1]/'public',port=0);server.start()
   address='127.0.0.1:'+str(server.server_address[1])
   def request(method,path,headers=None,body=None):
    c=http.client.HTTPConnection(address);c.request(method,path,body=body,headers=headers or {});r=c.getresponse();result=(r.status,r.read());c.close();return result
   try:
    self.assertEqual(request('GET','/')[0],302)
    code,raw=request('GET','/api/campo');self.assertEqual(code,200);self.assertEqual(json.loads(raw)['accounts'],[])
    self.assertEqual(json.loads(request('GET','/api/app')[1])['mode'],'web')
    self.assertEqual(request('POST','/api/campo',{'Origin':'http://'+address,'Content-Type':'application/json'},'{}')[0],403)
    headers={'Origin':'http://'+address,'X-Console-CSRF':server.campo.csrf,'Content-Type':'application/json'}
    self.assertEqual(request('POST','/api/campo',headers,json.dumps({'action':'add','label':'Test'}))[0],200)
    self.assertEqual(request('GET','/api/campo',{'Host':'evil.example'})[0],403)
    for path in ['/console','/desk','/blog','/launch','/api/desktop/check-update']:
     self.assertEqual(request('POST' if '/api/' in path else 'GET',path)[0],404)
   finally:server.close()
