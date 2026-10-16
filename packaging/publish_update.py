"""Sign and stage release assets. The signing key is never shipped to clients."""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from updater import canonical,version,verify_manifest,verified_file

def publish(installer,release_version,notes,directory,key_path,public_path):
 version(release_version);installer=Path(installer);directory=Path(directory)
 with installer.open('rb') as f:
  if f.read(2)!=b'MZ':raise ValueError('Installer is not a Windows executable')
 key=Ed25519PrivateKey.from_private_bytes(Path(key_path).read_bytes())
 expected=base64.b64decode(Path(public_path).read_text().strip(),validate=True)
 if key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)!=expected:raise ValueError('Signing key does not match client public key')
 directory.mkdir(parents=True,exist_ok=True)
 digest=hashlib.sha256()
 with installer.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
 name='CampoReader-Setup-'+release_version+'-Windows-x64.exe'
 feed=directory/'update.json'
 if feed.exists():
  old=verify_manifest(json.loads(feed.read_text('utf-8')),expected)
  if version(old['version'])>version(release_version):raise ValueError('Refusing a channel downgrade')
  if old['version']==release_version:
   if old['installer']['sha256']!=digest.hexdigest():raise ValueError('A released version is immutable; bump the version')
   if verified_file(directory/name,old['installer']):return old
 target=directory/name;part=target.with_suffix('.tmp')
 try:os.link(installer,part)
 except OSError:shutil.copyfile(installer,part)
 os.replace(part,target)
 payload={'version':release_version,'platform':'windows-x64','published_at':datetime.now(timezone.utc).isoformat(),'notes':notes,'installer':{'file':name,'size':installer.stat().st_size,'sha256':digest.hexdigest()}}
 envelope={'payload':payload,'signature':base64.b64encode(key.sign(canonical(payload))).decode()}
 verify_manifest(envelope,expected)
 temp=directory/'update.json.new';temp.write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,feed)
 # Existing download links continue to work, now pointing to the current installer.
 alias=directory/'CampoReader-Setup-Windows-x64.exe';temp=directory/'setup-alias.new'
 try:temp.unlink(missing_ok=True);os.link(target,temp);os.replace(temp,alias)
 finally:temp.unlink(missing_ok=True)
 return payload

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('installer');p.add_argument('version');p.add_argument('--notes-file',required=True);p.add_argument('--directory',required=True);p.add_argument('--key',required=True);args=p.parse_args()
 result=publish(args.installer,args.version,Path(args.notes_file).read_text('utf-8'),args.directory,args.key,Path(__file__).resolve().parents[1]/'update-public-key.txt')
 print('Published signed Campo Reader update '+result['version'])
