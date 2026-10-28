"""Shared timetable UI against the real local HTTP backend, desktop and phone layers."""
import sys,tempfile,shutil
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from web import WebServer
from server import ASSETS
from campo_backend.campo_source.core import BERLIN
from campo_backend.browser import launch_browser
from playwright.sync_api import sync_playwright,expect
for android in (False,True):
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder);public=root/'public';shutil.copytree(ROOT/'public',public)
  if android:
   for file in (ROOT/'android/app/src/main/mobile').glob('*'):shutil.copy(file,public/file.name)
   p=public/'campo-reader.html';p.write_text(p.read_text().replace('</head>','<link rel="stylesheet" href="/android-mobile.css"><script defer src="/android-mobile.js"></script></head>'))
   ASSETS.update({'/android-mobile.css':('android-mobile.css','text/css'),'/android-mobile.js':('android-mobile.js','text/javascript')})
  server=WebServer(root,public,port=0);campo=server.campo;user=campo.public_user;account=campo.action(user,{'action':'add','label':'Timetable test'})['account'];server.start()
  try:
   with sync_playwright() as p:
    browser=launch_browser(p);page=browser.new_page(viewport={'width':393 if android else 1366,'height':900},is_mobile=android,has_touch=android);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept());page.add_init_script('window.CampoMobile={about(){},checkUpdate(){},exportPdf(){}}');page.goto(server.origin+'/tools/campo-reader');page.locator('#lesson-add').wait_for(state='visible')
    today=datetime.now(BERLIN).date();first=today-timedelta(days=today.weekday());date=first.isoformat()
    page.locator('#lesson-add').click();page.locator('#lesson-title').fill('Single lesson');page.locator('#lesson-date').fill(date);page.locator('#lesson-save').click();expect(page.locator('#lesson-dialog')).not_to_be_visible();expect(page.locator('.manual-course')).to_have_count(1)
    if android:expect(page.locator('.manual-course')).to_be_visible()
    page.locator('#lesson-add').click();page.locator('#lesson-title').fill('Weekly lesson');page.locator('#lesson-date').fill(date);page.locator('#lesson-repeat').select_option('weekly');page.locator('#lesson-until').fill((first+timedelta(days=14)).isoformat());page.locator('#lesson-weekdays input[value="0"]').check();page.locator('#lesson-weekdays input[value="2"]').check();page.locator('#lesson-save').click();expect(page.locator('#lesson-dialog')).not_to_be_visible();expect(page.locator('.manual-course')).to_have_count(3)
    page.locator('.manual-course').filter(has_text='Weekly lesson').first.click();page.locator('#detail-actions').get_by_role('button',name='修改这一节').click();page.locator('#lesson-title').fill('Moved lesson');page.locator('#lesson-save').click();expect(page.locator('.manual-course').filter(has_text='Moved lesson')).to_have_count(1)
    page.locator('#lesson-manage').click();expect(page.locator('.lesson-item')).to_have_count(2);page.locator('.lesson-item').filter(has_text='Weekly lesson').get_by_role('button',name='删除',exact=True).click();expect(page.locator('.lesson-item')).to_have_count(1)
    page.reload();expect(page.locator('.manual-course')).to_have_count(1);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors,errors;browser.close()
  finally:server.close()
print('Shared desktop and Android phone manual timetable: passed')
