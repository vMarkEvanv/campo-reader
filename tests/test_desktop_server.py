import http.client
import json
import tempfile
import unittest
from pathlib import Path
from server import DesktopServer

class DesktopServerTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.opened=[];self.server=DesktopServer(Path(self.temp.name),Path(__file__).resolve().parents[1]/'public',lambda:self.opened.append(True));self.server.start();self.addCleanup(self.server.close)
  status,_,headers=self.request('GET','/launch?token='+self.server.secret,auth=False)
  self.assertEqual(status,302);self.cookie=headers['Set-Cookie'].split(';')[0]
 def request(self,method,path,body=None,auth=True,extra=None):
  headers={}
  if auth:headers['Cookie']=self.cookie
  if method=='POST':headers.update({'Origin':self.server.origin,'Content-Type':'application/json','X-Console-CSRF':self.server.campo.csrf})
  headers.update(extra or {})
  c=http.client.HTTPConnection(self.server.address,timeout=10);c.request(method,path,json.dumps(body).encode() if body is not None else None,headers);r=c.getresponse();raw=r.read();result=(r.status,raw,dict(r.getheaders()));c.close();return result
 def test_local_only_with_no_anonymous_api_or_other_origin(self):
  self.assertEqual(self.server.server_address[0],'127.0.0.1')
  self.assertEqual(self.request('GET','/api/campo',auth=False)[0],403)
  self.assertEqual(self.request('GET','/api/campo',extra={'Host':'attacker.example'})[0],403)
  self.assertEqual(self.request('POST','/api/campo',{'action':'add','label':'A'},extra={'Origin':'https://attacker.example'})[0],403)
  self.assertEqual(self.request('POST','/api/campo',{'action':'add','label':'A'},extra={'X-Console-CSRF':'wrong'})[0],403)
 def test_account_create_document_download_and_restart_data(self):
  status,raw,_=self.request('POST','/api/campo',{'action':'add','label':'A'});self.assertEqual(status,200);account=json.loads(raw)['account']
  import base64
  pdf=b'%PDF-1.4\n%%EOF';status,raw,_=self.request('POST','/api/campo',{'action':'document-upload','id':account,'title':'Proof','content':base64.b64encode(pdf).decode()});self.assertEqual(status,200)
  doc=json.loads(raw)['workspace']['documents'][0]['id'];status,raw,headers=self.request('GET','/api/campo/document?id='+account+'&document_id='+doc);self.assertEqual(status,200);self.assertEqual(raw,pdf);self.assertIn('attachment',headers['Content-Disposition'])
  from campo_backend.campo import Campo
  restored=Campo(Path(self.temp.name));self.assertEqual(restored.snapshot(restored.public_user,account)['workspace']['documents'][0]['id'],doc)
 def test_only_campo_assets_and_folder_action(self):
  for path in ['/tools/campo-reader','/campo-reader.js','/campo-workspace.js','/work-theme.css']:
   self.assertEqual(self.request('GET',path)[0],200)
  for path in ['/console','/api/console/state','/blog','/data/campo/calendar.key','/../desktop.py']:
   self.assertEqual(self.request('GET',path)[0],404)
  self.assertEqual(self.request('POST','/api/desktop/open-data')[0],200);self.assertEqual(self.opened,[True])

 def test_launch_token_and_session_are_per_instance(self):
  self.assertEqual(self.request('GET','/launch?token=incorrect',auth=False)[0],403)
  with tempfile.TemporaryDirectory() as other:
   another=DesktopServer(Path(other),self.server.public)
   try:self.assertNotEqual(self.server.secret,another.secret);self.assertNotEqual(self.server.cookie_name,another.cookie_name)
   finally:another.server_close()
 def test_payload_limit_and_malformed_request_are_rejected(self):
  self.assertEqual(self.request('POST','/api/campo',[],extra={})[0],400)
  self.assertEqual(self.request('POST','/api/campo',{'action':'add','label':'A'},extra={'Content-Type':'text/plain'})[0],415)
  self.assertEqual(self.request('POST','/api/console/send',{})[0],404)
