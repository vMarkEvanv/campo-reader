import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
import updater as u

class UpdateTests(unittest.TestCase):
 def setUp(self):
  self.private=Ed25519PrivateKey.generate();self.key=self.private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
  self.data=b'MZ'+b'x'*200
  self.payload={'version':'1.2.0','platform':'windows-x64','published_at':'2026-10-16T00:00:00Z','notes':'New version','installer':{'file':'CampoReader-Setup-1.2.0-Windows-x64.exe','size':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest()}}
 def signed(self,payload=None):
  p=payload or self.payload;return {'payload':p,'signature':base64.b64encode(self.private.sign(u.canonical(p))).decode()}
 def session(self,data):
  session=MagicMock();r=MagicMock();r.status_code=200;r.headers={'Content-Length':str(len(data))};r.iter_content.return_value=[data];session.get.return_value=r;r.__enter__.return_value=r;return session,r
 def test_signature_tampering_and_invalid_manifest(self):
  self.assertEqual(u.verify_manifest(self.signed(),self.key)['version'],'1.2.0')
  bad=self.signed();bad['payload']['version']='9.0.0'
  with self.assertRaises(u.UpdateError):u.verify_manifest(bad,self.key)
  for field,value in [('file','../bad.exe'),('size',True),('sha256','wrong')]:
   p=copy.deepcopy(self.payload);p['installer'][field]=value
   with self.assertRaises(u.UpdateError):u.verify_manifest(self.signed(p),self.key)
 def test_version_comparison_and_no_downgrade(self):
  self.assertGreater(u.version('1.10.0'),u.version('1.9.9'))
  for current in ['1.2.0','1.3.0']:
   s,_=self.session(json.dumps(self.signed()).encode());self.assertIsNone(u.check_update(self.key,current,session=s))
  for invalid in ['1.2','1.2.3-beta','-1.2.3',None]:
   with self.assertRaises(u.UpdateError):u.version(invalid)
 def test_validated_download_cancellation_and_corruption(self):
  with tempfile.TemporaryDirectory() as root:
   p=dict(self.payload,download_url=u.release_url(self.payload['version'],self.payload['installer']['file']))
   s,_=self.session(self.data);path=u.download_update(p,root,session=s);self.assertTrue(u.verified_file(path,p['installer']))
   s,_=self.session(b'bad');self.assertEqual(u.download_update(p,root,session=s),path);s.get.assert_not_called()
   path.unlink();s,r=self.session(self.data[:-1]+b'z')
   with self.assertRaises(u.UpdateError):u.download_update(p,root,session=s)
   self.assertFalse(path.exists());self.assertFalse(list(Path(root).rglob('*.part')))
   event=threading.Event();event.set()
   with self.assertRaises(u.Cancelled):u.download_update(p,root,event,session=s)
   p['download_url']='https://attacker.example/file.exe'
   with self.assertRaises(u.UpdateError):u.download_update(p,root,session=s)
 def test_settings_do_not_touch_business_data_and_arguments_are_not_shell_text(self):
  with tempfile.TemporaryDirectory() as root:
   data=Path(root)/'account.sqlite3';data.write_bytes(b'preserve')
   u.save_settings(root,{'auto_check':False,'last_attempt':10});self.assertFalse(u.load_settings(root)['auto_check']);self.assertEqual(data.read_bytes(),b'preserve')
  args=u.installer_arguments('C:/User Name/update.exe','C:/Program Name')
  self.assertIsInstance(args,list);self.assertIn('/DIR=C:/Program Name',args);self.assertNotIn('/FORCECLOSEAPPLICATIONS',args)
 def test_publisher_signs_channel_and_rejects_version_replacement(self):
  from packaging_publish import publish
  from cryptography.hazmat.primitives.serialization import PrivateFormat,NoEncryption
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);installer=root/'setup.exe';installer.write_bytes(self.data);key=root/'key';key.write_bytes(self.private.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()));pub=root/'pub';pub.write_text(base64.b64encode(self.key).decode());out=root/'out'
   publish(installer,'1.2.0','notes',out,key,pub)
   result=u.verify_manifest(json.loads((out/'update.json').read_text()),self.key);self.assertEqual(result['version'],'1.2.0')
   installer2=root/'other.exe';installer2.write_bytes(b'MZother')
   with self.assertRaises(ValueError):publish(installer2,'1.2.0','changed',out,key,pub)

 def test_github_redirects_are_restricted_and_pinned_to_signed_version(self):
  s,r=self.session(json.dumps(self.signed()).encode())
  redirect=MagicMock();redirect.status_code=302;redirect.headers={'Location':'https://release-assets.githubusercontent.com/github-production-release-asset/example'}
  s.get.side_effect=[redirect,r]
  p=u.check_update(self.key,'1.0.0',session=s)
  self.assertEqual(p['download_url'],u.release_url('1.2.0',self.payload['installer']['file']))
  redirect.close.assert_called_once()
  for bad in ['http://github.com/vMarkEvanv/campo-reader/releases/file','https://attacker.example/file','https://github.com/other/repo/releases/file','https://github.com.evil.example/file']:
   s,r=self.session(b'');redirect=MagicMock();redirect.status_code=302;redirect.headers={'Location':bad};s.get.return_value=redirect
   with self.assertRaises(u.UpdateError):u.check_update(self.key,'1.0.0',session=s)
   self.assertEqual(s.get.call_count,1)
