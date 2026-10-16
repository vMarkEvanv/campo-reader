"""Windows CI: upgrade 1.2.1 using the actual detached helper, then check user data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from campo_backend.campo import Campo
from version import VERSION

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def main():
 root=Path(__file__).resolve().parents[1];install=Path(tempfile.mkdtemp(prefix='campo-upgrade-')).resolve()/'app'
 old=root/'old-release/CampoReader-Setup-Windows-x64.exe';new=root/'release/CampoReader-Setup-Windows-x64.exe';bundle=root/'dist/CampoReader/CampoReader.exe'
 print('Installing previous release',flush=True)
 subprocess.run([str(old),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/DIR='+str(install)],check=True,timeout=90)
 data=Path(os.environ['LOCALAPPDATA'])/'CampoReader';data.mkdir(exist_ok=True)
 marker=data/'update-preserve-marker.txt';marker.write_text('preserve my data',encoding='utf-8')
 campo=Campo(data);account=campo.action(campo.public_user,{'action':'add','label':'Upgrade test'})['account']
 doc=campo.action(campo.public_user,{'action':'document-upload','id':account,'title':'Proof','content':base64.b64encode(b'%PDF-1.4\n%%EOF').decode()})['workspace']['documents'][0]['id']
 cache=data/'updates';cache.mkdir(exist_ok=True);cached=cache/('CampoReader-Setup-'+VERSION+'-Windows-x64.exe')
 import shutil
 shutil.copyfile(new,cached)
 parent=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],creationflags=subprocess.CREATE_NO_WINDOW)
 before=digest(install/'CampoReader.exe')
 helper=subprocess.Popen([str(bundle),'--apply-update',str(cached),'--sha256',digest(cached),'--size',str(cached.stat().st_size),'--wait-pid',str(parent.pid),'--target-dir',str(install)])
 time.sleep(2);assert digest(install/'CampoReader.exe')==before,'Installer changed files before parent exit'
 parent.terminate();parent.wait(timeout=10);assert helper.wait(timeout=90)==0
 print('Detached helper completed; waiting for new installed app',flush=True)
 target_hash=digest(bundle);deadline=time.monotonic()+100;ids=[]
 env=dict(os.environ,CAMPO_TEST_EXE=str((install/'CampoReader.exe').resolve()))
 command="Get-Process CampoReader -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $env:CAMPO_TEST_EXE } | Select-Object -ExpandProperty Id"
 while time.monotonic()<deadline:
  if (install/'CampoReader.exe').exists() and digest(install/'CampoReader.exe')==target_hash:
   r=subprocess.run(['powershell','-NoProfile','-Command',command],env=env,capture_output=True,text=True,timeout=10)
   ids=[int(v) for v in r.stdout.split() if v.isdigit()]
   if ids:break
  time.sleep(2)
 if not ids:
  print('installed_exe_exists', (install/'CampoReader.exe').exists(), flush=True)
  print('installed_exe_matches', (install/'CampoReader.exe').exists() and digest(install/'CampoReader.exe')==target_hash, flush=True)
  error=data/'startup-error.txt'
  if error.exists():print('startup_error_type',error.read_text(),flush=True)
  log=cache/'installer.log'
  if log.exists():print('installer_log_tail',log.read_text('utf-8-sig',errors='replace')[-16000:],flush=True)
  else:print('No installer log was created',flush=True)
  print(subprocess.run(['powershell','-NoProfile','-Command',"Get-Process CampoReader*,*Setup* -ErrorAction SilentlyContinue | Select-Object Id,Path | Format-Table -AutoSize"],capture_output=True,text=True,timeout=10).stdout,flush=True)
 assert ids,'Updated app did not restart'
 for pid in ids:subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,timeout=20)
 time.sleep(2)
 restored=Campo(data);assert restored.snapshot(restored.public_user,account)['accounts'][0]['label']=='Upgrade test'
 assert restored.document(restored.public_user,account,doc)[1]==b'%PDF-1.4\n%%EOF'
 assert marker.read_text('utf-8')=='preserve my data'
 subprocess.run([str(install/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True,timeout=90)
 assert marker.read_text('utf-8')=='preserve my data'
 assert Campo(data).document(campo.public_user,account,doc)[1]==b'%PDF-1.4\n%%EOF'
 report={'ok':True,'version':VERSION,'waited_for_parent':True,'actual_upgrade':True,'app_restarted':True,'account_preserved':True,'pdf_preserved':True,'uninstall_preserved_data':True}
 (root/'release/update-install-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main()
