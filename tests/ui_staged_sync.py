"""The browser shows a committed timetable while the same sync job is still running."""
import sys,tempfile,time
from pathlib import Path
from datetime import datetime,timedelta
from playwright.sync_api import sync_playwright
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from web import WebServer
from campo_backend.campo_source.core import BERLIN
with tempfile.TemporaryDirectory() as root:
 s=WebServer(Path(root),REPO/'public',port=0);c=s.campo;u=c.public_user;a=c.action(u,{'action':'add','label':'Fixture'})['account'];binding={'identity':'Fixture','fingerprint':'fixture'}
 c.commit_sync(u,a,dict(binding,events=[],grades=[]),None,None)
 c.jobs[(u,a)]={'running':True,'message':'正在读取成绩…'};s.start()
 try:
  with sync_playwright() as pw:
   b=pw.chromium.launch(executable_path='/usr/bin/chromium-browser',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
   page=b.new_page(viewport={'width':393,'height':852});errors=[];requests=[]
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url) if '/api/campo' in r.url else None)
   page.goto('http://127.0.0.1:'+str(s.server_address[1])+'/tools/campo-reader');page.locator('#identity',has_text='Fixture').wait_for();assert page.locator('#sync-progress').is_visible()
   initial=len([r for r in requests if 'status=1' not in r]);page.wait_for_timeout(1700);assert len([r for r in requests if 'status=1' not in r])==initial
   # Keep an unsent account form open: partial updates must not overwrite user input.
   page.locator('#add').evaluate('e=>{e.disabled=false;e.click()}');page.locator('#label').fill('Unsent text')
   today=datetime.now(BERLIN).replace(hour=10,minute=0,second=0,microsecond=0);end=today+timedelta(hours=1)
   c.commit_sync(u,a,dict(binding,events=[{'title':'Fresh timetable','start':today.isoformat(),'end':end.isoformat(),'room':'R1'}],calendar_updated_at=today.isoformat()),None,None)
   page.locator('#week .course strong',has_text='Fresh timetable').wait_for(state='attached',timeout=7000)
   assert c.jobs[(u,a)]['running'];assert page.locator('#sync-progress').is_visible();assert page.locator('#label').input_value()=='Unsent text'
   assert page.locator('#add-dialog').is_visible();page.locator('#add-dialog [data-close]').click()
   stable=len([r for r in requests if 'status=1' not in r]);page.wait_for_timeout(1800);assert len([r for r in requests if 'status=1' not in r])==stable
   c.jobs[(u,a)].update(running=False,message='课表已更新；成绩更新未完成。')
   page.locator('#sync-progress').wait_for(state='hidden',timeout=7000);assert page.locator('#week .course strong',has_text='Fresh timetable').count()==1
   page.reload();page.locator('#week .course strong',has_text='Fresh timetable').wait_for(state='attached');assert not errors,errors
   b.close();print('Staged sync UI: timetable shown mid-job, unchanged progress stays lightweight, open form retained, partial failure and reload preserve timetable.')
 finally:s.close()
