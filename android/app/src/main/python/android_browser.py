"""Narrow Playwright-compatible adapter backed by Android's on-device WebView.
Only the read-only operations used by campo_backend are implemented. No remote driver.
"""
import contextlib,json,time,tempfile
from pathlib import Path
from urllib.parse import urlsplit
from campo_backend.campo_source.core import DataError

def official(url):
    u=urlsplit(url)
    return u.scheme=='https' and (u.hostname=='fau.de' or (u.hostname or '').endswith('.fau.de')) and u.port in (None,443) and not u.username and not u.password

def native():
    from java import jclass
    return jclass('io.github.vmarkevanv.camporeader.CampoApplication').instance.browser

def rpc(op,**args):
    result=json.loads(str(native().call(op,json.dumps(args,ensure_ascii=True))))
    if not result.get('ok'):raise DataError(result.get('error') or '手机浏览器操作未完成，请重新同步。')
    return result.get('value')

class Locator:
    def __init__(self,page,selector=None,name=None):self.page,self.selector,self.name=page,selector,name
    @property
    def first(self):return self
    def expression(self):
        if self.selector:return 'document.querySelector('+json.dumps(self.selector)+')'
        return 'Array.from(document.querySelectorAll("a,[role=link]")).find(e=>(e.innerText||e.getAttribute("aria-label")||"").trim()==='+json.dumps(self.name)+')'
    def is_visible(self):return self.page.evaluate('(()=>{const e='+self.expression()+';return !!e&&!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)})()')
    def click(self,timeout=10000,no_wait_after=False):
        deadline=time.monotonic()+timeout/1000
        while not self.is_visible():
            if time.monotonic()>deadline:raise DataError('Campo 操作入口未出现，原有数据保留。')
            self.page.wait_for_timeout(150)
        if not self.page.evaluate('(()=>{const e='+self.expression()+';if(!e)return false;e.click();return true})()'):raise DataError('Campo 按钮已失效，请重试。')
        if not no_wait_after:self.page.wait_for_timeout(250);self.page.wait_for_load_state()
    def select_option(self,value=None,**kwargs):
        if not self.page.evaluate('(()=>{const e='+self.expression()+';if(!e||!Array.from(e.options).some(o=>o.value==='+json.dumps(value)+'))return false;e.value='+json.dumps(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));return true})()'):raise DataError('Campo 学期选项未识别，原有数据保留。')

class Download:
    def __init__(self,path):self._path=path
    def path(self):return self._path

class Page:
    def __init__(self,context):self.context=context;self.listeners={};self.timeout=25000
    def set_default_timeout(self,n):self.timeout=n
    def on(self,name,fn):self.listeners.setdefault(name,[]).append(fn)
    def remove_listener(self,name,fn):
        if fn in self.listeners.get(name,[]):self.listeners[name].remove(fn)
    def _downloads(self):
        for url in rpc('downloads') or []:
            if not official(url):continue
            # Native WebView reports the final official PDF URL, including HttpOnly cookies.
            from campo_backend.campo_workspace import fetch_pdf
            cookies={c['name']:c['value'] for c in self.context.cookies(url)}
            try:content=fetch_pdf(url,cookies)
            except DataError:continue
            fd=tempfile.NamedTemporaryFile(suffix='.pdf',dir=self.context.temp,delete=False);fd.write(content);fd.close()
            for fn in list(self.listeners.get('download',[])):fn(Download(fd.name))
    def goto(self,url,wait_until=None,timeout=25000):
        if not official(url):raise DataError('仅允许连接 FAU 官方 HTTPS 地址。')
        rpc('goto',url=url);self.wait_for_load_state(timeout=timeout)
    def evaluate(self,script):return rpc('evaluate',script=script)
    def wait_for_timeout(self,ms):
        time.sleep(ms/1000);self._downloads()
    def wait_for_load_state(self,state=None,timeout=25000):
        deadline=time.monotonic()+timeout/1000
        while time.monotonic()<deadline:
            status=rpc('status')
            if status.get('error'):raise DataError('Campo 网页加载失败，请检查网络后重试。')
            if not status.get('loading'):
                idle=self.evaluate('(()=>document.readyState==="complete"&&(!window.jQuery||!jQuery.active)&&(!window.PrimeFaces||!PrimeFaces.ajax||!PrimeFaces.ajax.Queue||PrimeFaces.ajax.Queue.isEmpty()))()')
                if idle:return
            self.wait_for_timeout(150)
        raise DataError('Campo 网页加载超时，旧数据保留。')
    @contextlib.contextmanager
    def expect_navigation(self,**kwargs):
        previous=rpc('status').get('sequence',0)
        yield
        deadline=time.monotonic()+self.timeout/1000
        while rpc('status').get('sequence',0)<=previous:
            if time.monotonic()>deadline:raise DataError('登录页面没有响应，请重新同步。')
            time.sleep(.1)
        self.wait_for_load_state(timeout=self.timeout)
    def locator(self,selector):return Locator(self,selector)
    def get_by_role(self,role,name='',exact=True):return Locator(self,name=name)

class Context:
    def __init__(self,storage_state=None,**kwargs):
        import tempfile
        self._temp=tempfile.TemporaryDirectory(prefix='campo-pdf-');self.temp=self._temp.name;self.listeners={};self.page=None
        rpc('reset',state=storage_state or {'cookies':[],'origins':[]})
    def route(self,pattern,guard):pass  # Native WebView enforces FAU HTTPS allowlist for every request.
    def new_page(self):self.page=Page(self);return self.page
    def storage_state(self):return {'cookies':rpc('cookies'),'origins':[]}
    def cookies(self,url):return [c for c in rpc('cookies') if urlsplit(url).hostname==c['domain'].lstrip('.') or urlsplit(url).hostname.endswith('.'+c['domain'].lstrip('.'))]
    def on(self,name,fn):self.listeners.setdefault(name,[]).append(fn)
    def remove_listener(self,name,fn):
        if fn in self.listeners.get(name,[]):self.listeners[name].remove(fn)
    def close(self):rpc('close');self._temp.cleanup()
class Browser:
    def __init__(self):self.context=None
    def new_context(self,**kwargs):self.context=Context(**kwargs);return self.context
    def close(self):
        if self.context:self.context.close();self.context=None
class Factory:
    @property
    def chromium(self):return self
    def launch(self,**kwargs):return Browser()
@contextlib.contextmanager
def sync_playwright():yield Factory()
