"""Signed GitHub Releases update channel. No client token or private server."""
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

RELEASE_ROOT='https://github.com/vMarkEvanv/campo-reader/releases/'
FEEDS=(RELEASE_ROOT+'latest/download/update.json',)
ASSET_HOSTS={'release-assets.githubusercontent.com','objects.githubusercontent.com'}

def release_url(release_version,filename):
 version(release_version)
 return RELEASE_ROOT+'download/v'+release_version+'/'+filename

def github_location(url):
 u=urlsplit(url)
 if u.scheme!='https' or u.username or u.password or u.port not in (None,443):return False
 if u.hostname in ASSET_HOSTS:return True
 return u.netloc=='github.com' and u.path.startswith('/vMarkEvanv/campo-reader/releases/')

def fetch(http,url,timeout):
 # Follow GitHub's asset CDN redirects, rejecting other hosts and HTTP downgrades.
 for _ in range(6):
  if not github_location(url):raise UpdateError('更新来源验证失败，请稍后重试。')
  r=http.get(url,timeout=timeout,stream=True,allow_redirects=False)
  if r.status_code not in (301,302,303,307,308):return r
  location=r.headers.get('Location');r.close()
  if not location:raise UpdateError('无法获取有效的下载地址。')
  url=urljoin(url,location)
 raise UpdateError('无法连接更新下载服务，请稍后重试。')

MAX_SIZE=2*1024*1024*1024
class UpdateError(Exception):pass
class Cancelled(UpdateError):pass

def version(value):
 if not isinstance(value,str) or not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}',value):raise UpdateError('版本信息不正确。')
 return tuple(map(int,value.split('.')))
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
def cancelled(event):
 if event is not None and event.is_set():raise Cancelled('已取消。')
def verify_manifest(envelope,key):
 try:
  payload=envelope['payload'];signature=base64.b64decode(envelope['signature'],validate=True)
  Ed25519PublicKey.from_public_bytes(key).verify(signature,canonical(payload))
  version(payload['version']);asset=payload['installer']
  if payload['platform']!='windows-x64' or type(asset['size']) is not int or not 0<asset['size']<=MAX_SIZE:raise ValueError()
  if not re.fullmatch(r'[a-f0-9]{64}',asset['sha256']):raise ValueError()
  if not re.fullmatch(r'CampoReader-Setup-[0-9.]+-Windows-x64\.exe',asset['file']):raise ValueError()
  if not isinstance(payload.get('notes',''),str) or len(payload.get('notes',''))>16000:raise ValueError()
  if not isinstance(payload.get('published_at'),str):raise ValueError()
 except Exception:raise UpdateError('更新信息验证失败，未执行下载或安装。') from None
 return payload

def check_update(key,current,event=None,feeds=FEEDS,session=None):
 version(current);http=session or requests.Session()
 for feed in feeds:
  cancelled(event)
  try:
   with fetch(http,feed,(5,15)) as r:
    if r.status_code!=200:continue
    raw=b''
    for block in r.iter_content(8192):
     cancelled(event);raw+=block
     if len(raw)>65536:raise UpdateError('更新信息过大。')
    payload=verify_manifest(json.loads(raw),key)
    if version(payload['version'])<=version(current):return None
    payload=dict(payload,download_url=release_url(payload['version'],payload['installer']['file']))
    return payload
  except Cancelled:raise
  except UpdateError:raise
  except (requests.RequestException,ValueError,KeyError,TypeError):continue
 raise UpdateError('暂时无法连接更新服务，请检查网络后重试。')

def verified_file(path,asset,event=None):
 path=Path(path)
 if not path.is_file() or path.stat().st_size!=asset['size']:return False
 digest=hashlib.sha256()
 with path.open('rb') as f:
  if f.read(2)!=b'MZ':return False
  f.seek(0)
  while True:
   cancelled(event);block=f.read(1024*1024)
   if not block:break
   digest.update(block)
 return hmac.compare_digest(digest.hexdigest(),asset['sha256'])

def download_update(payload,root,event=None,progress=None,session=None):
 asset=payload['installer'];version(payload['version'])
 # Manifest does not control a local path or permit downloading arbitrary URLs.
 url=payload['download_url']
 if url!=release_url(payload['version'],asset['file']):raise UpdateError('更新下载地址不正确。')
 folder=Path(root)/'updates';folder.mkdir(parents=True,exist_ok=True)
 target=folder/asset['file'];part=folder/(asset['file']+'.part')
 if verified_file(target,asset,event):return target
 http=session or requests.Session()
 try:
  cancelled(event)
  with fetch(http,url,(5,20)) as r:
   if r.status_code!=200:raise UpdateError('更新包下载失败，请稍后重试。')
   length=r.headers.get('Content-Length')
   if length and int(length)!=asset['size']:raise UpdateError('更新包大小不符合发布信息。')
   total=0;digest=hashlib.sha256()
   with part.open('wb') as f:
    for block in r.iter_content(256*1024):
     cancelled(event)
     if not block:continue
     total+=len(block)
     if total>asset['size']:raise UpdateError('更新包超出预期大小。')
     f.write(block);digest.update(block)
     if progress:progress(total,asset['size'])
    f.flush();os.fsync(f.fileno())
   if total!=asset['size'] or not hmac.compare_digest(digest.hexdigest(),asset['sha256']):raise UpdateError('更新包校验失败，已丢弃下载内容。')
   with part.open('rb') as f:
    if f.read(2)!=b'MZ':raise UpdateError('下载内容不是有效的 Windows 安装包。')
   os.replace(part,target);return target
 except Cancelled:raise
 except UpdateError:raise
 except (requests.RequestException,OSError,ValueError):raise UpdateError('下载中断或磁盘空间不足，请重试。') from None
 finally:
  try:part.unlink(missing_ok=True)
  except OSError:pass

def load_settings(root):
 try:
  d=json.loads((Path(root)/'update-settings.json').read_text('utf-8'))
  return {'auto_check':d.get('auto_check',True) is True,'last_attempt':float(d.get('last_attempt',0))}
 except (OSError,ValueError,TypeError,AttributeError):return {'auto_check':True,'last_attempt':0}
def save_settings(root,settings):
 path=Path(root)/'update-settings.json';temp=path.with_suffix('.tmp')
 temp.write_text(json.dumps(settings),encoding='utf-8');os.replace(temp,path)

def installer_arguments(installer,target):
 return [str(installer),'/SILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/UPDATE=1','/LOG='+str(Path(installer).parent/'installer.log'),'/DIR='+str(target)]

def apply_update(installer,sha256,size,wait_pid,target,root):
 """Detached helper waits for the old app to exit before starting the installer."""
 if sys.platform!='win32':raise UpdateError('只能在 Windows 上安装更新。')
 path=Path(installer).resolve();folder=(Path(root)/'updates').resolve()
 if path.parent!=folder or not re.fullmatch(r'CampoReader-Setup-[0-9.]+-Windows-x64\.exe',path.name):raise UpdateError('安装包路径不正确。')
 if not verified_file(path,{'size':size,'sha256':sha256}):raise UpdateError('安装前校验失败。')
 import ctypes
 from ctypes import wintypes
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
 kernel.CloseHandle.argtypes=[wintypes.HANDLE]
 handle=kernel.OpenProcess(0x00100000,False,wait_pid)
 if handle:
  try:
   if kernel.WaitForSingleObject(handle,120000)!=0:raise UpdateError('原程序尚未退出，更新未执行。')
  finally:kernel.CloseHandle(handle)
 # External installers must not inherit the frozen app's DLL search directory.
 kernel.SetDllDirectoryW.argtypes=[wintypes.LPCWSTR];kernel.SetDllDirectoryW(None)
 subprocess.Popen(installer_arguments(path,Path(target).resolve()),env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1'),close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
