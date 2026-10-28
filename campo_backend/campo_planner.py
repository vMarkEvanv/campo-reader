"""Read-only Study Planner catalog. No exam/course registration controls are submitted."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
import requests
from .campo_source.core import HOME,HOST,DataError
from .campo_workspace import credits,stamp,stable

class Node:
    def __init__(self,tag='',attrs=(),parent=None):
        self.tag=tag;self.attrs=dict(attrs);self.parent=parent;self.children=[];self.parts=[]
    @property
    def text(self):return re.sub(r'\s+',' ',''.join(p.text if isinstance(p,Node) else p for p in self.parts)).strip()
    def find(self,tag=None):
        for child in self.children:
            if tag is None or child.tag==tag:yield child
            yield from child.find(tag)

class DOM(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.root=Node();self.current=self.root;self.feed(html)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs,self.current);self.current.children.append(node);self.current.parts.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:self.current=node
    def handle_endtag(self,tag):
        node=self.current
        while node.parent and node.tag!=tag:node=node.parent
        if node.parent:self.current=node.parent
    def handle_data(self,text):self.current.parts.append(text)

def validate_identity(dom,expected):
    avatar=next((n for n in dom.find() if n.attrs.get('id','').endswith('avatarInfobox:open')),None)
    identity=(avatar.attrs.get('title') or avatar.attrs.get('data-title') or avatar.attrs.get('aria-label') or '') if avatar else ''
    identity=re.sub(r'^(My profile|Mein Profil)\s*:\s*','',identity,flags=re.I)
    identity=re.split(r'\s+(Student|Studierende|Studierender|Friedrich-Alexander)',identity,flags=re.I)[0].strip()
    if not expected or identity!=expected or not any(n.attrs.get('id','').endswith('logoutLink') for n in dom.find()):
        raise DataError('FAU 登录已过期或 Study Planner 身份不一致，原有学分保留。')

def request(http,url,expected,method='GET',data=None):
    for _ in range(6):
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname!=HOST or u.port not in (None,443) or not u.path.startswith('/qisserver/'):
            raise DataError('Study Planner 请求地址不正确，原有学分保留。')
        try:
            with http.request(method,url,data=data,timeout=(10,45),allow_redirects=False,stream=True) as r:
                if r.status_code in (301,302,303,307,308):
                    url=urljoin(url,r.headers.get('Location',''))
                    if r.status_code in (301,302,303):method='GET';data=None
                    continue
                if r.status_code!=200:raise DataError('Study Planner 读取失败，原有学分保留。')
                chunks=[];size=0
                for chunk in r.iter_content(65536):
                    size+=len(chunk)
                    if size>12*1024*1024:raise DataError('Study Planner 内容过大，原有学分保留。')
                    chunks.append(chunk)
                dom=DOM(b''.join(chunks).decode(r.encoding or 'utf-8',errors='replace')).root
        except requests.RequestException:raise DataError('Study Planner 网络读取失败，原有学分保留。') from None
        validate_identity(dom,expected);return url,dom
    raise DataError('Study Planner 重定向次数过多。')

def post_view(http,url,dom,expected,button_id,view=None):
    if button_id not in ('enrollTree:switchView','enrollTree:expandAll'):raise DataError('不支持的 Study Planner 操作。')
    button=next((n for n in dom.find('button') if n.attrs.get('id')==button_id),None)
    if not button:raise DataError('Study Planner 视图入口未识别。')
    form=button.parent
    while form and form.tag!='form':form=form.parent
    if not form or form.attrs.get('id')!='enrollTree':raise DataError('Study Planner 视图表单未识别。')
    payload={}
    for n in form.find('input'):
        if n.attrs.get('name') and (n.attrs.get('type') not in ('radio','checkbox','submit','button','password','file') or 'checked' in n.attrs):
            payload[n.attrs['name']]=n.attrs.get('value','')
    for n in form.find('select'):
        options=list(n.find('option'));chosen=[o for o in options if 'selected' in o.attrs] or options[:1]
        if chosen and n.attrs.get('name'):payload[n.attrs['name']]=chosen[0].attrs.get('value',chosen[0].text)
    payload['enrollTree:_idcl']=button_id
    if button.attrs.get('name'):payload[button.attrs['name']]=button.attrs.get('value','')
    if view:
        if view not in ('mplan','tree'):raise DataError('不支持的 Study Planner 视图。')
        payload['activeView']=view
    return request(http,urljoin(url,form.attrs.get('action','')),expected,'POST',payload)

def parse_modules(dom):
    table=next((n for n in dom.find('table') if 'modulePlan' in n.attrs.get('class','').split()),None)
    if table is None:raise DataError('Study Planner 模块计划未识别，旧目录保留。')
    heading=next((n.text for n in dom.find() if n.attrs.get('id')=='hisinoneTitle'),'')
    program=re.sub(r'^(?:Study planner with module plan|Studienplaner mit Modulplan)\s*','',heading,flags=re.I).strip()
    modules={}
    for card in table.find('div'):
        if 'headerModulePlan' not in card.attrs.get('class','').split():continue
        title=next((n.text for n in card.find('h3') if n.attrs.get('id','').endswith(':popupTitleId')),'')
        title_match=re.fullmatch(r'(.+?)\s+-\s+(.+)',title)
        value=next((n.text for n in card.children if n.tag=='span' and re.fullmatch(r'(?:-|\d+(?:[.,]\d+)?)\s*/\s*\d+(?:[.,]\d+)?',n.text)),'')
        value_match=re.fullmatch(r'(?:-|\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)',value)
        if not title_match or not value_match:continue
        number,name=title_match.groups();value=credits(value_match[1])
        if value is None or not 0<=value<=120:continue
        key=stable(program,number)
        row={'id':key,'program':program,'number':number[:80],'name':name[:200],'credits':value,'courses':[]}
        if key in modules and modules[key]['credits']!=value:raise DataError('Study Planner 同一模块学分冲突，旧目录保留。')
        modules[key]=row
    if not modules:raise DataError('Study Planner 未读取到模块学分，旧目录保留。')
    return list(modules.values())

def exact_name(value):
    value=re.sub(r'^\s*\d+\s*\|\s*','',value)
    value=re.sub(r'^(?:Lecture with exercise|Tutorial/exercise|Online Course|Lecture|Vorlesung mit Übung|Vorlesung)\s+','',value,flags=re.I)
    return re.sub(r'[^\w]+',' ',value.casefold()).strip()

def parse_tree(dom,modules):
    from urllib.parse import parse_qs
    table=next((n for n in dom.find('table') if 'treeTableWithIcons' in n.attrs.get('class','').split()),None)
    if table is None:raise DataError('Study Planner 课程层级未识别，旧目录保留。')
    stack=[]
    def add(container,name,value,link):
        match=re.search(r'(\d+(?:[.,]\d+)?)\s*ECTS',value,re.I)
        numeric=credits(match[1]) if match else None
        unit=parse_qs(urlsplit(link.attrs.get('href','')).query).get('unitId',[''])[0]
        if not name or numeric is None or not 0<=numeric<=120:return
        record={'name':name[:240],'credits':numeric,'unit_id':unit if unit.isdigit() else ''}
        for m in container:
            if record not in m['courses']:m['courses'].append(record)
    for row in table.find('tr'):
        depth=re.search(r'treeTableCellLevel(\d+)',row.attrs.get('class',''))
        if not depth:continue
        depth=int(depth[1])
        while stack and stack[-1][0]>=depth:stack.pop()
        anchor=next((a for a in row.find('a') if 'linkTableTree' in a.attrs.get('class','').split()),None)
        if anchor is None:continue
        aid=anchor.attrs.get('id','')
        if aid.endswith(':showModuleLink:link'):
            number=anchor.text.split('|',1)[0].strip()
            parents=[m for m in modules if m['number']==number]
            stack.append((depth,parents))
            for unit in row.find('div'):
                if not unit.attrs.get('id','').endswith(':hiddenUnit'):continue
                link=next((a for a in unit.find('a') if 'unitId=' in a.attrs.get('href','')),None)
                label=next(unit.find('button'),None)
                if link and label:add(parents,label.attrs.get('value') or label.text,unit.text,link)
        elif aid.endswith(':showPlanelementLink:link') and stack:
            value=next((s.text for s in row.find('span') if s.attrs.get('title')=='Credit Points'),'')
            add(stack[-1][1],anchor.text,value+' ECTS',anchor)
    if not any(m['courses'] for m in modules):raise DataError('Study Planner 未读取到课程学分，旧目录保留。')
    return modules

def credit_index(catalog):
    rows=catalog.get('modules',[]) if isinstance(catalog,dict) else []
    result={}
    for module in rows:
        for course in module.get('courses',[]):
            result.setdefault(exact_name(course.get('name','')),[]).append(course)
    return result

def credit_lookup(catalog,course,index=None):
    index=credit_index(catalog) if index is None else index
    name=exact_name(course.get('name',''))
    matches=index.get(name,[]) if name else []
    values={c['credits'] for c in matches}
    if len(values)==1:
        units={c.get('unit_id','') for c in matches}
        return next(iter(values)),next(iter(units)) if len(units)==1 else '','study_planner_course'
    return None,'','unknown'


def collect(snapshot,expected):
    with requests.Session() as http:
        for cookie in snapshot.get('cookies',[]):
            if cookie.get('domain','').lstrip('.')==HOST:
                http.cookies.set(cookie['name'],cookie['value'],domain=cookie['domain'],path=cookie.get('path','/'))
        url,dom=request(http,HOME,expected)
        link=next((a for a in dom.find('a') if re.search(r'Study planner with module plan|Studienplaner mit Modulplan',a.text,re.I)),None)
        if not link:raise DataError('Study Planner 入口未找到，旧目录保留。')
        url,dom=request(http,urljoin(url,link.attrs.get('href','')),expected)
        if not any('modulePlan' in n.attrs.get('class','').split() for n in dom.find('table')):
            url,dom=post_view(http,url,dom,expected,'enrollTree:switchView','mplan')
        modules=parse_modules(dom)
        url,dom=post_view(http,url,dom,expected,'enrollTree:switchView','tree')
        url,dom=post_view(http,url,dom,expected,'enrollTree:expandAll')
        parse_tree(dom,modules)
        return {'modules':modules,'checked_at':stamp()}
