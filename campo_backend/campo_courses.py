"""Read course enrollments independently of exam registrations."""
import re
import json
import time
from .campo_source.core import HOME,DataError
from .campo_documents import activate,identity
from .campo_workspace import stable,credits,stamp

NAV = r'''(() => Array.from(document.querySelectorAll('a,button')).map(e=>({id:e.id,label:(e.innerText||e.getAttribute('aria-label')||e.title||'').replace(/\s+/g,' ').trim(),href:e.tagName==='A'?e.href:''})).filter(e=>/^(Belegungen\s*\/\s*Enrollments?|Enrollments?|Belegungen|Meine Belegungen|My enrollments)$/i.test(e.label)))()'''
TABLES = r'''(() => ({empty:/no (?:enrollments|courses|data) (?:available|found)|keine (?:belegungen|veranstaltungen|daten)/i.test(document.body.innerText||''),term:Array.from(document.querySelectorAll('select')).flatMap(e=>Array.from(e.selectedOptions)).map(e=>e.textContent.trim()).find(v=>/semester|summer|winter|\b[WS]S\s*20/i.test(v))||'',tables:Array.from(document.querySelectorAll('table')).map(t=>{const headers=Array.from(t.querySelectorAll('thead th')).map(e=>e.innerText.replace(/\s+/g,' ').trim());const first=Array.from(t.rows).find(r=>Array.from(r.cells).some(c=>c.tagName==='TH'));const parent=t.closest('.datatable')||t.parentElement;return {caption:(parent.querySelector('h2.table_caption')||{}).innerText||'',headers:headers.length?headers:first?Array.from(first.cells).map(c=>c.innerText.replace(/\s+/g,' ').trim()):[],rows:Array.from(t.querySelectorAll('tbody tr')).filter(r=>r!==first && !r.querySelector('th')).map(r=>({cells:Array.from(r.cells).map(c=>c.innerText.replace(/\s+/g,' ').trim()),type:r.getAttribute('data-type')||''})).slice(0,500)}}).filter(t=>t.headers.length)}))()'''

ALIASES={'name':['veranstaltung','veranstaltungstitel','bezeichnung','titel','title','course','course title','event','event title','name'], 'number':['nummer','number','course number','veranstaltungsnummer','nr.'], 'status':['status','belegstatus','enrollment status','zulassung'], 'kind':['art','typ','type','veranstaltungsart'], 'credits':['ects','ects-punkte','credits','credit points','ects credits'], 'semester':['semester','term'], 'module_number':['modulnummer','module number']}

def term_key(value):
    year=re.search(r'20\d{2}',value or '')
    if year:
        if re.search(r'winter|\bws\b|\bwise\b',value,re.I):return year[0]+'W'
        if re.search(r'sommer|summer|\bss\b|\bsose\b',value,re.I):return year[0]+'S'
    return (value or '').strip()

def parse_tables(payload,fallback_term=''):
    if not isinstance(payload,dict) or not isinstance(payload.get('tables'),list):raise DataError('课程报名列表未识别，保留原有课程。')
    term=payload.get('term') or fallback_term
    courses={};recognized=False;tables=[]
    for table in payload['tables']:
        headers=[str(h).strip().lower() for h in table.get('headers',[])]
        columns={k:next((i for i,h in enumerate(headers) if h in names),None) for k,names in ALIASES.items()}
        if columns['name'] is None:
            caption=table.get('caption','').strip()
            if re.match(r'^(Course|Veranstaltung)\s*:',caption,re.I) and columns['status'] is not None and any(h in ('dates and rooms','termine und räume') for h in headers):
                table=dict(table,headers=['Name']+table['headers'],rows=[dict(r,cells=[caption]+r.get('cells',[])) for r in table.get('rows',[])])
                headers=['name']+headers
                columns={k:next((i for i,h in enumerate(headers) if h in names),None) for k,names in ALIASES.items()}
            else:continue
        # A grades or exam-only table is not a course enrollment list.
        if any(h in ('note','grade','versuch','attempt') for h in headers):continue
        recognized=True;tables.append(headers)
        for row in table.get('rows',[]):
            cells=row.get('cells',[])
            def read(k):
                i=columns[k]
                return str(cells[i]).strip() if i is not None and i<len(cells) else ''
            name=re.sub(r'^(Course|Veranstaltung)\s*:\s*','',read('name'),flags=re.I);kind=read('kind') or row.get('type','');status=read('status')
            if not name or re.search(r'exam|prüfung|pruefung|klausur',kind,re.I):continue
            semester=read('semester') or term
            status_term=re.search(r'\b(WiSe|SoSe|WS|SS|Winter semester|Summer semester|Wintersemester|Sommersemester)\s*(20\d{2}(?:/\d{2,4})?)',status,re.I)
            if status_term:
                explicit=' '.join(status_term.groups())
                if term_key(explicit)!=term_key(semester):semester=explicit
            # Explicit row semesters remain distinct even in an all-semester view.
            source_id=read('number') or name
            key=stable('enrollment',source_id,term_key(semester))
            active=not re.search(r'^(AB|ST|WL)$|abgemeldet|storniert|withdrawn|cancelled|warteliste|waiting list|rejected|abgelehnt',status,re.I)
            courses[key]={'id':key,'name':name[:200],'number':read('number')[:80],'semester':semester[:80],'status':status[:100] or '报名列表记录','kind':kind[:80],'credit_value':credits(read('credits')),'module_number':read('module_number')[:80],'source':'enrollments','active':active,'confirmed_enrollment':True}
    if not recognized:
        error=DataError('Enrollments 中未识别到课程表；不会把考试报名表当作课程。')
        error.schema=[table.get('headers',[]) for table in payload['tables']]
        raise error
    return list(courses.values()),{'checked_at':stamp(),'source':'Enrollments / Belegungen','message':'已读取课程报名列表。','count':len(courses),'semester':term}

def collect(page,expected,semester='',current_only=False):
    page.goto(HOME,wait_until='domcontentloaded',timeout=25000);identity(page,expected)
    controls=page.evaluate(NAV)
    if not isinstance(controls,list) or not controls:raise DataError('首页未找到 Enrollments / Belegungen 入口，课程报名尚未更新。')
    activate(page,controls[0]);page.wait_for_timeout(700);identity(page,expected)
    selectors=page.evaluate(TERM_SELECTS)
    if not selectors:raise DataError('学期选择器未识别，原有全部学期课程保留。')
    selector=selectors[0]
    terms=[o for o in selector['options'] if not o['disabled'] and re.search(r'20\d{2}',o['label']) and re.search(r'semester|winter|summer|sommer|\bWS\b|\bSS\b|WiSe|SoSe',o['label'],re.I)]
    if current_only:
        terms=[o for o in terms if term_key(o['label'])==term_key(semester)]
    result={};completed=[]
    for option in terms:
        control=page.locator('[id='+json.dumps(selector['id'])+']')
        control.select_option(option['value']);page.wait_for_timeout(500)
        page.wait_for_load_state('networkidle',timeout=20000);page.wait_for_timeout(500);identity(page,expected)
        deadline=time.monotonic()+20
        while True:
            payload=page.evaluate(TABLES)
            try:rows,_=parse_tables(payload,option['label'])
            except DataError:
                captions=[t.get('caption','') for t in payload.get('tables',[])]
                if (not captions and payload.get('empty')) or (captions and all(re.match(r'^(Examination|Exam|Prüfung)\s*:',v,re.I) for v in captions)):rows=[]
                else:raise
            if term_key(payload.get('term',''))==term_key(option['label']) and all(term_key(r['semester'])==term_key(option['label']) for r in rows):break
            if time.monotonic()>=deadline:raise DataError('学期内容尚未加载完成，原有课程保留。')
            page.wait_for_timeout(500);identity(page,expected)
        for row in rows:result[row['id']]=row
        completed.append(option['label'])
    if not completed:raise DataError('没有识别到可读取的学期，原有课程保留。')
    return list(result.values()),{'checked_at':stamp(),'source':'Enrollments / Belegungen','message':('已更新当前学期课程；历史课程保留。' if current_only else '已读取全部 '+str(len(completed))+' 个可用学期的课程报名。'),'count':len(result),'semesters':completed,'scope':'current' if current_only else 'all'}

TERM_SELECTS = r'''(() => Array.from(document.querySelectorAll('select')).map(e=>({id:e.id,name:e.name,change:e.getAttribute('onchange')||'',options:Array.from(e.options).map(o=>({value:o.value,label:o.textContent.trim(),disabled:o.disabled}))})).filter(e=>e.id && e.options.some(o=>/20\d{2}/.test(o.label)&&/semester|winter|summer|sommer|\bWS\b|\bSS\b|WiSe|SoSe/i.test(o.label))))()'''
