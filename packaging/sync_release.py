"""Owner-side release mirror. GitHub credentials and signing key stay on this device."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from publish_update import publish
from updater import version

REPO='vMarkEvanv/campo-reader'
def main():
 p=argparse.ArgumentParser();p.add_argument('--gh',required=True);p.add_argument('--directory',required=True);p.add_argument('--key',required=True);a=p.parse_args()
 def gh(*args):return subprocess.check_output([a.gh,*args],text=True,timeout=180)
 release=json.loads(gh('api','repos/'+REPO+'/releases/latest'))
 v=release['tag_name'].removeprefix('v');version(v)
 directory=Path(a.directory);feed=directory/'update.json'
 if feed.exists() and version(json.loads(feed.read_text())['payload']['version'])>=version(v):
  print('Update channel is current');return
 names=['CampoReader-Setup-Windows-x64.exe','SHA256SUMS.txt','smoke-windows.json','update-install-smoke.json']
 with tempfile.TemporaryDirectory(prefix='campo-release-') as tmp:
  for name in names:gh('release','download','v'+v,'--repo',REPO,'--pattern',name,'--dir',tmp)
  root=Path(tmp);sums={}
  for line in (root/'SHA256SUMS.txt').read_text('utf-8-sig').splitlines():
   digest,name=line.split(None,1);sums[name.strip()]=digest
  for name in names:
   if name=='SHA256SUMS.txt':continue
   h=hashlib.sha256()
   with (root/name).open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
   if h.hexdigest()!=sums.get(name):raise ValueError('Release checksum mismatch')
  for name in ['smoke-windows.json','update-install-smoke.json']:
   report=json.loads((root/name).read_text('utf-8-sig'))
   if not report.get('ok') or report.get('version')!=v:raise ValueError('Windows validation report failed')
  publish(root/names[0],v,release.get('body',''),directory,a.key,Path(__file__).resolve().parents[1]/'update-public-key.txt')
  for name in names[1:]:
   target=directory/name;part=target.with_suffix('.new');part.write_bytes((root/name).read_bytes());part.replace(target)
  index=directory/'index.html'
  if index.exists():
   import re
   text=index.read_text()
   text=re.sub(r'(WINDOWS DESKTOP · )\d+\.\d+\.\d+',lambda m:m[1]+v,text)
   text=re.sub(r'(/releases/(?:download|tag)/v)\d+\.\d+\.\d+',lambda m:m[1]+v,text)
   size=round((root/names[0]).stat().st_size/(1024*1024))
   text=re.sub(r'(Windows 10 / 11 x64 · )\d+ MB',lambda m:m[1]+str(size)+' MB',text)
   part=index.with_suffix('.new');part.write_text(text);part.replace(index)
 print('Published verified Windows release '+v)
if __name__=='__main__':main()
