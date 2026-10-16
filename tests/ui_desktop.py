import sys,tempfile
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from server import DesktopServer
from desktop_updates import UpdateController
from campo_backend.browser import launch_browser
from unittest.mock import patch
from playwright.sync_api import sync_playwright
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);srv=DesktopServer(root,REPO/'public');c=srv.campo;u=c.public_user;a=c.action(u,{'action':'add','label':'Test account'})['account']
 data={'identity':'Test','fingerprint':'test','events':[],'grades':[{'kind':'module','name':'Course '+str(i),'number':str(i),'program':'Test','status':'BE','credits':'5','grade':'1.3'} for i in range(90)]}
 s=c.store(u);s.save(a,data);s.close();controller=UpdateController(root,REPO);srv.updates=controller;srv.start()
 try:
  with patch('desktop_updates.updater.check_update',return_value=None),sync_playwright() as pw:
   browser=launch_browser(pw);page=browser.new_page(viewport={'width':1366,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(srv.launch_url);page.locator('[data-desktop-menu-trigger]').wait_for();page.locator('#tab-grades').click();page.locator('#grade-kind').select_option('module');page.locator('#grade-rows tr').first.wait_for()
   assert page.evaluate("getComputedStyle(document.documentElement,'::-webkit-scrollbar').width")=='6px'
   assert page.evaluate("getComputedStyle(document.documentElement).backgroundColor")=='rgb(16, 19, 21)'
   assert page.locator('.tablewrap').evaluate("e=>getComputedStyle(e,'::-webkit-scrollbar').height")=='6px'
   assert page.evaluate('document.documentElement.scrollHeight>innerHeight')
   page.locator('[data-desktop-menu-trigger]').click();page.get_by_role('menuitem',name='关于 Campo Reader').click();about=page.locator('.desktop-about-dialog');about.wait_for()
   for term in ['Orange Pi','orangepi','WebView2','GitHub','开发']:assert term not in about.inner_text()
   page.wait_for_timeout(180);page.screenshot(path=str(root/'about-preview.png'));about.get_by_role('button',name='关闭').click()
   page.evaluate("window.dispatchEvent(new Event('campo-update-open'))");page.locator('.desktop-update-dialog').wait_for();page.wait_for_timeout(180)
   for term in ['Orange Pi','orangepi','WebView2','GitHub','开发']:assert term not in page.locator('.desktop-update-dialog').inner_text()
   page.screenshot(path=str(root/'update-preview.png'));page.locator('.desktop-update-dialog [data-close]').click()
   page.locator('#settings').click();assert '密码不保存' not in page.locator('#settings-dialog').inner_text();page.locator('#settings-dialog [data-close]').first.click()
   assert not errors,errors
   browser.close();print('Clean about/update/settings copy; root/table rounded 6px scrollbars; no JS errors: passed')
 finally:controller.shutdown();srv.close()
