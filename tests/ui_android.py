"""Packaged mobile assets tested against an isolated shared backend, no FAU login."""
import sys,tempfile,shutil
from pathlib import Path
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from web import WebServer
from server import ASSETS
from playwright.sync_api import sync_playwright
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);public=root/'public';shutil.copytree(REPO/'public',public)
 for p in (REPO/'android/app/src/main/mobile').glob('*'):shutil.copy(p,public/p.name)
 p=public/'campo-reader.html';p.write_text(p.read_text().replace('</head>','<link rel="stylesheet" href="/android-mobile.css"><script defer src="/android-mobile.js"></script></head>'))
 ASSETS.update({'/android-mobile.css':('android-mobile.css','text/css'),'/android-mobile.js':('android-mobile.js','text/javascript')})
 server=WebServer(root,public,port=0);campo=server.campo;u=campo.public_user;a=campo.action(u,{'action':'add','label':'Mobile test'})['account']
 store=campo.store(u);store.save(a,{'fingerprint':'synthetic','identity':'Synthetic','events':[],'grades':[],'courses':[{'id':'test','name':'A long synthetic lecture title that wraps onto another line','semester':'WS 2026/27','source':'enrollments','confirmed_enrollment':True,'active':True,'credit_value':3}]});store.close();server.start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium-browser',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
   for width in [360,393,600]:
    page=browser.new_page(viewport={'width':width,'height':852},is_mobile=True,has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script('window.CampoMobile={about(){},exportPdf(){}}')
    page.goto('http://127.0.0.1:'+str(server.server_address[1])+'/tools/campo-reader');page.locator('#android-about').wait_for();page.locator('#identity',has_text='Synthetic').wait_for()
    assert page.locator('#week>.mobile-day-active').count()==1
    assert page.locator('.mobile-days button').count()==7
    page.locator('.mobile-days button').nth(1).click();assert page.locator('#week>.mobile-day-active').get_attribute('data-day-index')=='1'
    page.locator('#tab-courses').click();page.locator('#course-list .course-row').wait_for();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#course-list button',has_text='学习类型与学分').click();assert page.locator('#course-dialog').is_visible()
    page.locator('#course-exam').select_option('exercise_credit');page.locator('#course-credits').fill('2.25');page.locator('#course-form .primary').click();page.locator('#courses-classified').click();page.locator('#course-list .course-type-badge',has_text='练习课 · 有学分').wait_for()
    for view in ['grades','progress','documents','calendar']:
     page.locator('#tab-'+view).click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),view
    if width==393:page.screenshot(path='/tmp/campo-android-mobile.png',full_page=True)
    assert not errors,errors
    # Return shared fixture to unclassified for the next viewport.
    rev=campo.snapshot(u,a)['workspace']['revision'];campo.action(u,{'id':a,'action':'courses-batch','revision':rev,'course_ids':['test'],'purpose':'undecided'})
    page.close()
   browser.close();print('Android packaged mobile UI: day navigation, small-screen layouts, course editing and all views passed.')
 finally:server.close()
