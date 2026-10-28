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

 def test_status_endpoint_and_compressed_revalidated_assets(self):
  import gzip
  with tempfile.TemporaryDirectory() as root:
   public=Path(root)/'public';public.mkdir();original=b'/* test asset */\n'*200
   (public/'campo-reader.css').write_bytes(original)
   server=WebServer(Path(root),public,port=0);server.start()
   def request(path,headers=None):
    conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1]);conn.request('GET',path,headers=headers or {});r=conn.getresponse();result=(r.status,dict(r.getheaders()),r.read());conn.close();return result
   try:
    account=server.campo.action(server.campo.public_user,{'action':'add','label':'A'})['account']
    code,headers,raw=request('/api/campo?id='+account+'&status=1')
    self.assertEqual(code,200);self.assertEqual(set(json.loads(raw)),{'account','job','csrf'})
    self.assertEqual(headers['Cache-Control'],'no-store')
    code,headers,raw=request('/campo-reader.css',{'Accept-Encoding':'gzip'})
    self.assertEqual(code,200);self.assertEqual(gzip.decompress(raw),original)
    self.assertLess(len(raw),len(original));etag=headers['ETag']
    code,_,raw=request('/campo-reader.css',{'Accept-Encoding':'gzip','If-None-Match':etag})
    self.assertEqual((code,raw),(304,b''))
    (public/'campo-reader.css').write_bytes(original+b'changed')
    code,headers,raw=request('/campo-reader.css',{'Accept-Encoding':'gzip','If-None-Match':etag})
    self.assertEqual(code,200);self.assertNotEqual(headers['ETag'],etag)
    code,headers,raw=request('/campo-reader.css',{'Accept-Encoding':'gzip;q=0'})
    self.assertNotIn('Content-Encoding',headers);self.assertTrue(raw.endswith(b'changed'))
   finally:server.close()
