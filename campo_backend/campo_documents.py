"""Read Campo Documents navigation and download only selected official reports."""
import hashlib
import json
import re
import time
from pathlib import Path
from .campo_source.core import HOME, DataError
from .campo_source import scripts
from .campo_workspace import safe_pdf_url, fetch_pdf, stamp, MAX_PDF

NAVIGATION = r'''(() => Array.from(document.querySelectorAll('a,button,[role=tab]')).map(e=>({id:e.id,label:(e.innerText||e.getAttribute('aria-label')||e.title||'').replace(/\s+/g,' ').trim(),href:e.tagName==='A'?e.href:'',role:e.getAttribute('role')||'',action:!!e.getAttribute('onclick'),selected:e.getAttribute('aria-selected')==='true',visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)})).filter(e=>/^(?:Bescheinigungen\s*\/\s*Documents?|Documents?|Bescheinigungen|Studienservice|Student services?|Study documents|Studiendokumente)$/i.test(e.label)))()'''
INDEX = r'''(() => Array.from(document.querySelectorAll('a,button,input[type=submit]')).map(e=>{const row=e.closest('tr,li')||e.parentElement;const label=(e.innerText||e.value||e.title||e.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();const marker=e.querySelector('img')||row?.querySelector('img');const pdf=/pdf/i.test((marker?.getAttribute('src')||'')+' '+(marker?.alt||'')+' '+e.title+' '+e.className);return {id:e.id,label,href:e.tagName==='A'?e.href:'',pdf,form:!!e.closest('form')};}).filter(e=>e.label && e.label.length<250 && (e.pdf||/\.pdf(?:[?#]|$)|reportFile|downloadReport|\/reporting\//i.test(e.href)) && !/anmelden|abmelden|logout|upload|delete|löschen|submit application/i.test(e.label)).slice(0,100))()'''

def key_for(title):return hashlib.sha256(title.casefold().encode()).hexdigest()[:24]
def category(title):
    if re.search('immatrikulation|enrol[ml]|studienbescheinigung',title,re.I):return 'enrolment'
    if re.search('transcript|noten|achievement',title,re.I):return 'transcript'
    if re.search('exam|prüfung',title,re.I):return 'exams'
    return 'other'

def identity(page, expected):
    state=page.evaluate(scripts.STATE)
    if not state or not state.get('logged_in'):raise DataError('FAU 登录已过期，请重新登录并同步。')
    if state.get('identity')!=expected:raise DataError('Documents 页面身份不一致，未保存文档。')

def locate(page, item):
    if item.get('id'):return page.locator('[id='+json.dumps(item['id'])+']').first
    return page.get_by_role('link',name=item.get('label',''),exact=True).first

def activate(page,item):
    href=item.get('href','')
    if href and safe_pdf_url(href) and not href.rstrip('/').endswith('#') and item.get('role')!='tab' and not item.get('action') and '#' not in href:
        page.goto(href,wait_until='domcontentloaded',timeout=25000)
    else:
        locate(page,item).click(timeout=10000)
        page.wait_for_timeout(500)

def read_index(page):
    raw=page.evaluate(INDEX)
    if not isinstance(raw,list):raise DataError('Documents 目录未能读取。')
    result={}
    for item in raw:
        if not isinstance(item,dict) or not item.get('label'):continue
        href=item.get('href','')
        if href and not href.startswith(('javascript:','#')) and not safe_pdf_url(href):continue
        title=item['label'].strip()
        if not item.get('id') and not href:continue
        result.setdefault(key_for(title),dict(item,key=key_for(title),title=title,category=category(title),language='en' if re.search('english|englisch',title,re.I) else 'de' if re.search('deutsch|german',title,re.I) else ''))
    return list(result.values())

def discover(page,expected):
    page.goto(HOME,wait_until='domcontentloaded',timeout=25000)
    identity(page,expected)
    controls=page.evaluate(NAVIGATION)
    if not isinstance(controls,list):raise DataError('未识别到 Documents 导航入口。')
    doc=[c for c in controls if c.get('visible',True) and re.search(r'documents?|bescheinigungen',c.get('label',''),re.I)]
    services=[c for c in controls if c.get('visible',True) and re.fullmatch(r'Studienservice|Student services?',c.get('label',''),re.I)]
    candidates=doc or services
    if not candidates:raise DataError('首页未找到 Documents / Bescheinigungen 入口。')
    activate(page,candidates[0]);page.wait_for_timeout(1000);identity(page,expected)
    # JSF tabs may be wrappers around a child link and render their body asynchronously.
    # Wait for a directory result; clicking a selected tab repeatedly can restart loading.
    deadline=time.monotonic()+15
    activated=set()
    while time.monotonic()<deadline:
        index=read_index(page)
        if index:return index
        controls=page.evaluate(NAVIGATION)
        tabs=[c for c in controls if c.get('visible',True) and re.fullmatch(r'Documents?|Bescheinigungen|Study documents|Studiendokumente',c.get('label',''),re.I)]
        for selected in sorted(tabs,key=lambda c:c.get('role')!='tab'):
            key=selected['label'].casefold()
            if key in activated or selected.get('selected'):continue
            activate(page,selected);activated.add(key)
            break
        page.wait_for_timeout(300)
        identity(page,expected)
    raise DataError('已进入学生服务，但未读取到 Documents 文档列表；旧文件已保留。')

PARAMETERS = r'''(() => Array.from(document.querySelectorAll('[id*="jobConfigurationButtonsOverlay"] select')).filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).map(e=>({id:e.id,options:Array.from(e.options).map(o=>({label:o.textContent,value:o.value,selected:o.selected})).filter(o=>o.label.trim())})))()'''

def semester_options(page):
    options=page.evaluate(PARAMETERS)
    if not isinstance(options,list):return []
    return [field for field in options if any(re.search(r'semester|sommer|winter|\b[WS]S\s*20',o.get('label',''),re.I) for o in field.get('options',[]))]

def configure_report(page,requested_term=''):
    term=''
    for field in semester_options(page):
        choices=field['options']
        selected=next((o for o in choices if o['label'].strip()==requested_term),None) if requested_term else next((o for o in choices if o.get('selected')),None)
        if requested_term and not selected:raise DataError('该文档不提供所选学期，请刷新 Documents 后重选。')
        selected=selected or (choices[0] if choices else None)
        if not selected:raise DataError('请先选择文档学期。')
        page.locator('[id='+json.dumps(field['id'])+']').select_option(value=selected['value'])
        term=selected['label'].strip()
    page.locator('[id$="jobConfigurationButtonsOverlay:navigationBottom:startJob"]').click(timeout=10000,no_wait_after=True)
    return term

def collect(page,context,expected,requested_key=None,requested_term=""):
    index=discover(page,expected)
    catalog=[{k:item[k] for k in ('key','title','category','language')} for item in index]
    info={'checked_at':stamp(),'source':'Student services → Documents','catalog':catalog,'found':len(catalog),'message':'已找到 Campo Documents 文档目录。请选择文档获取并归档。'}
    if not requested_key:
        enrollment=next((item for item in index if item['category']=='enrolment'),None)
        if enrollment:
            try:
                locate(page,enrollment).click(timeout=10000,no_wait_after=True)
                page.wait_for_timeout(700)
                fields=semester_options(page)
                info['terms']=[o['label'].strip() for field in fields for o in field['options']]
                cancel=page.locator('[id$="jobConfigurationButtonsOverlay:navigationBottom:cancelConfiguration"]').first
                if cancel.is_visible():cancel.click(timeout=5000)
            except Exception:pass
        return [],info
    item=next((item for item in index if item['key']==requested_key),None)
    if not item:raise DataError('该文档不再出现在 Documents 中，请刷新目录。')
    identity(page,expected)
    cookies={c['name']:c['value'] for c in context.cookies('https://www.campo.fau.de')}
    content=None;report_term=''
    # A real direct PDF URL can be fetched without interacting with JSF.
    if safe_pdf_url(item.get('href','')) and re.search(r'\.pdf(?:[?#]|$)|reportFile|downloadReport',item['href'],re.I):
        try:content=fetch_pdf(item['href'],cookies)
        except DataError:pass
    if content is None:
        downloads=[];responses=[]
        def on_download(download):downloads.append(download)
        def on_response(response):
            if safe_pdf_url(response.url) and ('application/pdf' in response.headers.get('content-type','').lower() or '.pdf' in response.headers.get('content-disposition','').lower()):responses.append(response)
        def watch(p):p.on('download',on_download);p.on('response',on_response)
        watch(page);context.on('page',watch)
        try:
            locate(page,item).click(timeout=10000,no_wait_after=True)
            deadline=time.monotonic()+45
            configured=False
            while time.monotonic()<deadline and not downloads and not responses:
                if not configured:
                    start=page.locator('[id$="jobConfigurationButtonsOverlay:navigationBottom:startJob"]').first
                    if start.is_visible():
                        fields=semester_options(page)
                        info['terms']=[o['label'].strip() for field in fields for o in field['options']]
                        report_term=configure_report(page,requested_term)
                        configured=True
                page.wait_for_timeout(200)
            if downloads:
                path=downloads[0].path()
                if path and Path(path).stat().st_size<=MAX_PDF:content=Path(path).read_bytes()
            elif responses:
                response=responses[0]
                if int(response.headers.get('content-length','0') or 0)>MAX_PDF:raise DataError('文件超过 10 MB。')
                content=response.body()
        finally:
            page.remove_listener('download',on_download);page.remove_listener('response',on_response);context.remove_listener('page',watch)
    if not isinstance(content,bytes) or not content.startswith(b'%PDF-') or len(content)>MAX_PDF:
        raise DataError('该 Documents 文档尚未生成有效 PDF，原归档保留。')
    page.goto(HOME,wait_until='domcontentloaded',timeout=25000);identity(page,expected)
    info['message']='已从 Campo Documents 获取并归档：'+item['title']
    return [{'content':content,'title':item['title'],'category':item['category'],'language':item['language'],'term':report_term or '未限定学期'}],info
