import sys,tempfile
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from web import WebServer
from campo_backend.browser import launch_browser
from playwright.sync_api import sync_playwright
with tempfile.TemporaryDirectory() as root:
 server=WebServer(Path(root),REPO/'public',port=0)
 campo=server.campo;u=campo.public_user;a=campo.action(u,{'action':'add','label':'UI test'})['account']
 data={'identity':'Test','fingerprint':'test','synced_at':'2026-10-16T12:00:00+02:00','events':[],'grades':[],'courses':[{'id':'course','name':'Practice course','semester':'WS 2026/27','source':'enrollments','confirmed_enrollment':True,'active':True,'credit_value':3}]}
 store=campo.store(u);store.save(a,data);store.close()
 server.start()
 try:
  with sync_playwright() as pw:
   browser=launch_browser(pw)
   for width,height in [(1366,900),(390,844)]:
    rev=campo.snapshot(u,a)['workspace']['revision'];campo.action(u,{'id':a,'action':'courses-batch','revision':rev,'course_ids':['course'],'purpose':'undecided'})
    page=browser.new_page(viewport={'width':width,'height':height});errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
    page.goto('http://127.0.0.1:'+str(server.server_address[1])+'/tools/campo-reader');page.locator('#tab-courses').click();page.locator('#course-list .course-row').wait_for()
    assert page.locator('#tab-changes').count()==0
    assert page.locator('#changes').count()==0
    assert page.locator('#course-list select').count()==0
    assert page.locator('#course-list .course-type-badge').inner_text()=='待决定'
    page.locator('#course-list button',has_text='学习类型与学分').click()
    page.locator('#course-exam').select_option('exercise_credit');page.locator('#course-credits').fill('1.25');assert page.locator('#course-credits').evaluate('(n)=>n.checkValidity()');page.locator('#course-form button.primary').click()
    page.locator('#courses-classified').click();page.locator('#course-list .course-type-badge',has_text='练习课 · 有学分').wait_for()
    page.locator('#course-list button',has_text='学习类型与学分').click();assert page.locator('#course-exam').input_value()=='exercise_credit';assert page.locator('#course-credits').input_value()=='1.25';assert '1.25 ECTS' in page.locator('#course-list').inner_text()
    page.locator('#course-exam').select_option('false');page.locator('#course-form button.primary').click()
    page.locator('#course-list .course-type-badge',has_text='无考试计划').wait_for()
    writes=[]
    page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
    revision=campo.snapshot(u,a)['workspace']['revision']
    page.locator('#courses-type-filter').select_option('exercise_credit')
    assert page.locator('#course-list .course-row').count()==0
    page.locator('#courses-type-filter').select_option('false')
    assert page.locator('#course-list .course-row').count()==1
    page.locator('#courses-type-filter').select_option('')
    assert page.locator('#course-list .course-row').count()==1
    assert page.locator('#courses-batch-apply').count()==0
    assert page.locator('#courses-select-all').count()==0
    assert not writes,writes
    assert campo.snapshot(u,a)['workspace']['revision']==revision
    page.locator('#course-list button',has_text='学习类型与学分').click()
    page.locator('#course-credit-auto').click()
    assert page.locator('#course-credits').input_value()=='3.00'
    assert '课程报名' in page.locator('#course-credit-source').inner_text()
    page.locator('#course-form button.primary').click()
    page.locator('#course-list .grade-note',has_text='3.00 ECTS').wait_for()
    assert campo.snapshot(u,a)['workspace']['courses_view'][0]['credits_source']=='enrollment'
    for view in ['grades','progress','documents','calendar']:
     page.locator('#tab-'+view).click();assert page.locator('#'+view).is_visible()
    assert not errors,errors
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.close()
   browser.close();print('Desktop/mobile manual override and restoring automatic credit source: passed')
 finally:server.close()
