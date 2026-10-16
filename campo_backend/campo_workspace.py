"""Account-scoped Campo changes, exams, module planning and private PDF archive."""
import base64
import hashlib
import json
import re
import uuid
import unicodedata
from collections import defaultdict
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit
from .console import ConsoleError
from .campo_source.core import BERLIN, DataError

MAX_PDF = 10 * 1024 * 1024
LABELS = {'title':'标题','start':'开始时间','end':'结束时间','room':'地点','grade':'成绩','status':'状态','credits':'学分','name':'名称','released':'发布日期','annotation':'备注'}

def ensure(store):
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS workspace (account_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS changes (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS changes_account ON changes(account_id,created);
    CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, title TEXT NOT NULL, term TEXT NOT NULL, category TEXT NOT NULL, language TEXT NOT NULL, source TEXT NOT NULL, digest TEXT NOT NULL, content BLOB NOT NULL, created TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
    ''')

def stamp(): return datetime.now(BERLIN).isoformat()
def stable(*parts): return hashlib.sha256(json.dumps(parts,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
def grade_key(g): return stable(g.get('program',''),g.get('kind',''),g.get('number') or g.get('name',''),g.get('attempt',''))
def string(value, maximum=200, required=False):
    if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()): raise ConsoleError('字段为空或长度不正确。')
    return value.strip()
def number(value, maximum=1000):
    if type(value) not in (int,float) or not 0 <= value <= maximum: raise ConsoleError('学分必须是合理的非负数字。')
    return round(float(value),2)
def credits(value):
    s=str(value).strip().replace(',','.')
    return float(s) if re.fullmatch(r'\d+(?:\.\d+)?',s) else None

def change_items(old,new):
    if not old.get('synced_at'): return []
    result=[]
    def add(kind,action,title,before,after,fields):
        diff=[{'field':LABELS.get(k,k),'before':str(before.get(k,'')),'after':str(after.get(k,''))} for k in fields if before.get(k,'')!=after.get(k,'')]
        if diff or action!='changed':result.append({'kind':kind,'action':action,'title':title,'fields':diff})
    # Compare only the intersection of export windows. A rolling window is not a cancellation.
    start=max(old.get('range_start','0000'),new.get('range_start','0000'))
    end=min(old.get('range_end','9999'),new.get('range_end','9999'))
    groups=[]
    for source in (old,new):
        group=defaultdict(list)
        for event in source.get('events',[]):
            if start<=event.get('start','')[:10]<end:group[event.get('uid') or event.get('title','')].append(event)
        groups.append(group)
    for key in set(groups[0])|set(groups[1]):
        left=list(groups[0][key]);right=list(groups[1][key])
        # Match unchanged occurrences first, then same-day occurrences, then nearest within seven days.
        pairs=[]
        for a in list(left):
            b=next((b for b in right if b.get('start')==a.get('start')),None)
            if b is not None:pairs.append((a,b));left.remove(a);right.remove(b)
        for a in list(left):
            if not a.get('start'):continue
            try:
                candidates=sorted(right,key=lambda b:abs((datetime.fromisoformat(b['start'])-datetime.fromisoformat(a['start'])).total_seconds()))
                b=candidates[0] if candidates else None
                if b and abs((datetime.fromisoformat(b['start'])-datetime.fromisoformat(a['start'])).total_seconds())<=7*86400:
                    pairs.append((a,b));left.remove(a);right.remove(b)
            except (ValueError,KeyError,TypeError):pass
        for a,b in pairs:add('calendar','changed',b.get('title','课程'),a,b,('title','start','end','room'))
        for a in left:add('calendar','removed',a.get('title','课程'),a,{},('start','room'))
        for b in right:add('calendar','added',b.get('title','课程'),{},b,('start','room'))
    a={grade_key(g):g for g in old.get('grades',[])};b={grade_key(g):g for g in new.get('grades',[])}
    for key in set(a)|set(b):
        before,after=a.get(key,{}),b.get(key,{})
        add('grades','added' if not before else 'removed' if not after else 'changed',after.get('name') or before.get('name','成绩'),before,after,('name','grade','status','credits','released','annotation'))
    return result

def record_changes(store,account,old,new):
    when=stamp()
    for item in change_items(old,new):
        store.db.execute('INSERT INTO changes VALUES (?,?,?,?,?,0)',(uuid.uuid4().hex,account,item['kind'],json.dumps(item,ensure_ascii=False),when))
    store.db.execute('DELETE FROM changes WHERE account_id=? AND id NOT IN (SELECT id FROM changes WHERE account_id=? ORDER BY created DESC,rowid DESC LIMIT 2000)',(account,account))

def plan(store,account):
    row=store.db.execute('SELECT payload FROM workspace WHERE account_id=?',(account,)).fetchone()
    state=json.loads(row[0]) if row else {'revision':0,'groups':[],'assignments':{},'planned':[],'exams':[]}
    state.setdefault('course_choices',{})
    return state

def module_list(data):
    rows={}
    for g in data.get('grades',[]):
        if g.get('kind')!='module':continue
        key=stable(g.get('program',''),g.get('number') or g.get('name',''))
        row=dict(g,id=key,passed=str(g.get('status','')).strip().upper() in ('BE','BESTANDEN','PASSED'),credit_value=credits(g.get('credits','')))
        if key not in rows or row['passed']:rows[key]=row
    return list(rows.values())

def exam_list(data,personal):
    events=[e for e in data.get('events',[]) if re.search(r'\b(exam(?:ination)?|klausur|prüfung|pruefung)\b|考试',e.get('title','')+' '+e.get('description',''),re.I)]
    result=[];used=set()
    for g in data.get('grades',[]):
        if g.get('kind')!='exam' or str(g.get('status','')).strip().upper() not in ('AN','ZU','ANGEMELDET','REGISTERED','ZUGELASSEN'):continue
        candidates=[e for e in events if (g.get('number') and re.search(r'\b'+re.escape(g['number'])+r'\b',e.get('title','')+' '+e.get('description',''))) or (len(g.get('name',''))>3 and g['name'].lower() in e.get('title','').lower())]
        event=candidates[0] if len(candidates)==1 else {}
        if event:used.add(stable(event.get('uid'),event.get('start')))
        result.append({'id':grade_key(g),'title':g['name'],'program':g.get('program',''),'number':g.get('number',''),'status':g.get('status',''),'source':'grades','start':event.get('start',''),'room':event.get('room',''),'registration_deadline':'','withdrawal_deadline':''})
    for e in events:
        key=stable(e.get('uid'),e.get('start'))
        if key not in used:result.append({'id':key,'title':e['title'],'start':e.get('start',''),'room':e.get('room',''),'status':'报名状态未确认','source':'calendar','registration_deadline':'','withdrawal_deadline':''})
    return result+personal

def course_name(value):
    value=unicodedata.normalize('NFKC',value or '').casefold().strip()
    value=re.sub(r'^(?:(?:course|veranstaltung)\s*:\s*)?','',value)
    value=re.sub(r'^(?:lecture with exercise|tutorial/exercise|online course|lecture|tutorial|exercise|vorlesung mit übung|vorlesung|übung)\s+','',value)
    value=re.sub(r'\s+(?:exercises|tutorials|übungen)$','',value)
    return ' '.join(re.sub(r'[^\w]+',' ',value).split())

def course_module(row,modules):
    number=row.get('module_number')
    if number:
        matches=[m for m in modules if m.get('number')==number]
        return (matches[0],'number') if len(matches)==1 else (None,'ambiguous')
    name=course_name(row.get('name',''))
    matches=[m for m in modules if name and course_name(m.get('name',''))==name]
    return (matches[0],'name') if len(matches)==1 else (None,'ambiguous' if matches else '')

def course_credit_value(row,choice,module,personal):
    if choice.get('credits') is not None and not choice.get('credits_auto',False):return choice['credits'],'manual'
    if row.get('credit_value') is not None:return row['credit_value'],'enrollment'
    if module and module.get('credit_value') is not None:return module['credit_value'],'module'
    if personal.get('credits') is not None:return personal['credits'],'planned'
    return None,'unknown'

def course_list(data,state):
    raw=data.get('courses')
    if raw is None:
        raw=[];seen=set();now=datetime.now(BERLIN)
        for e in data.get('events',[]):
            try:
                start=datetime.fromisoformat(e['start']);end=datetime.fromisoformat(e['end'])
                if start.tzinfo is None:start=start.replace(tzinfo=BERLIN)
                if end.tzinfo is None:end=end.replace(tzinfo=BERLIN)
                if not now-timedelta(days=14)<=end or start>now+timedelta(days=84):continue
            except (KeyError,ValueError,TypeError):continue
            name=e.get('title','')
            if re.search(r'exam|prüfung|klausur|考试',name,re.I):continue
            key=stable('calendar-course',name,data.get('semester',''))
            if key in seen:continue
            seen.add(key);raw.append({'id':key,'name':name,'semester':data.get('semester',''),'number':'','credit_value':None,'module_number':'','source':'calendar_candidate','status':'课表候选 · 报名待确认','active':True,'confirmed_enrollment':False})
    rows={row['id']:dict(row) for row in raw}
    choices=state.get('course_choices',{})
    for key,choice in choices.items():
        if key not in rows and choice.get('source_snapshot'):rows[key]=dict(choice['source_snapshot'],active=False)
    modules=module_list(data)
    for key,row in rows.items():
        choice=choices.get(key,{})
        match,method=course_module(row,modules)
        explicit=choice.get('module_id','')
        module=next((m for m in modules if m['id']==explicit),None) if explicit else match
        default_module=module['id'] if module else ''
        link=explicit or default_module
        personal={}
        if explicit.startswith('planned:'):
            personal=next((p for p in state.get('planned',[]) if p['id']==explicit[8:]),{})
            module=next((m for m in modules if m['id']==personal.get('module_id')),None)
        row.update(module_override=explicit,broken_link=bool(explicit and explicit!='none' and not module and not any(p['id']==explicit[8:] for p in state.get('planned',[]) if explicit.startswith('planned:'))),completed=bool(module and module['passed']),matched_module_name=module['name'] if module else '',match_source='manual' if explicit else method)
        credit_value,credit_source=course_credit_value(row,choice,module,personal)
        row.update(credits_source=credit_source,exercise_credits=choice.get('exercise_credits',False),exercise=choice.get('exercise',False),will_exam=choice.get('will_exam'),group=choice.get('group',''),credits=credit_value,module_id=link,ongoing=choice.get('ongoing',True),confirmed=row.get('confirmed_enrollment',False) or choice.get('confirmed',False))
    for row in rows.values():row['classified']=bool(row.get('exercise')) or type(row.get('will_exam')) is bool
    return list(rows.values())

def credit_intent(row):
    """Credited exercises can earn credit without an examination; legacy exercises cannot."""
    return row.get('exercise_credits',False) is True if row.get('exercise') else row.get('will_exam') is True

def effective_assignments(data,state,courses):
    result=dict(state.get('assignments',{}));valid={g['id'] for g in state.get('groups',[])}
    proposed=defaultdict(set)
    for row in courses:
        if credit_intent(row) and row.get('group') in valid:
            link=row.get('module_id','')
            if link.startswith('planned:'):
                personal=next((p for p in state.get('planned',[]) if p['id']==link[8:]),{})
                link=personal.get('module_id','')
            if link:proposed[link].add(row['group'])
    for p in state.get('planned',[]):
        if credit_intent(p) and p.get('module_id') and p.get('group') in valid:proposed[p['module_id']].add(p['group'])
    for key,values in proposed.items():
        if key not in result and len(values)==1:result[key]=next(iter(values))
    return result

def progress_statistics(data,state,courses):
    modules=module_list(data);by_id={m['id']:m for m in modules};passed={m['id'] for m in modules if m['passed']}
    groups={g['id']:dict(g,earned=0.,ongoing=0.,unknown_earned=0,ongoing_modules=[]) for g in state['groups']}
    effective=effective_assignments(data,state,courses)
    for m in modules:
        group=groups.get(effective.get(m['id']))
        if group is not None and m['passed']:
            if m['credit_value'] is None:group['unknown_earned']+=1
            else:group['earned']+=m['credit_value']
    planned={p['id']:p for p in state['planned']};candidates=[]
    for p in state['planned']:
        if p.get('status')!='ongoing' or not credit_intent(p):continue
        link=p.get('module_id','');module=by_id.get(link)
        if module and module['passed']:continue
        candidates.append({'key':'module:'+link if module else 'planned:'+p['id'],'name':p['name'],'group':p['group'],'credits':module['credit_value'] if module and module['credit_value'] is not None else p.get('credits'),'course':None})
    for row in courses:
        reason=''
        if row.get('broken_link'):reason='broken_link'
        elif row.get('exercise') and not row.get('exercise_credits'):reason='exercise'
        elif not row.get('active'):reason='inactive'
        elif not row.get('ongoing'):reason='not_ongoing'
        elif not row.get('exercise') and row.get('will_exam') is False:reason='interest'
        elif not credit_intent(row):reason='undecided'
        elif not row.get('confirmed'):reason='unconfirmed'
        elif row.get('group') not in groups:reason='no_group'
        link=row.get('module_id','');module=by_id.get(link)
        if module and module['passed']:reason='already_passed'
        elif module and row.get('group') and effective.get(module['id']) and effective[module['id']]!=row['group']:reason='group_conflict'
        value=module['credit_value'] if module and module['credit_value'] is not None else row.get('credits')
        row['count_reason']=reason
        if reason:continue
        key='module:'+link if module else link if link.startswith('planned:') and link[8:] in planned else 'subject:'+stable(row.get('number') or course_name(row.get('name','')))
        if key.startswith('planned:'):
            p=planned[key[8:]]
            linked=by_id.get(p.get('module_id',''))
            if linked and linked['passed']:row['count_reason']='already_passed';continue
            if linked:key='module:'+linked['id'];value=linked['credit_value'] if linked['credit_value'] is not None else value
            elif value is None:value=p.get('credits')
        if value is None or value<=0:
            row['count_reason']='unknown_credits';continue
        candidates.append({'key':key,'name':row['name'],'group':row['group'],'credits':value,'course':row})
    buckets=defaultdict(list)
    for row in candidates:buckets[row['key']].append(row)
    for key,bucket in buckets.items():
        destinations={r['group'] for r in bucket};values={r['credits'] for r in bucket if r['credits'] is not None and r['credits']>0}
        reason='group_conflict' if len(destinations)>1 else 'credit_conflict' if len(values)>1 else 'unknown_credits' if not values else ''
        if reason:
            for r in bucket:
                if r['course'] is not None:r['course']['count_reason']=reason
            continue
        first=bucket[0];group=groups.get(first['group'])
        if group is None:continue
        value=next(iter(values));group['ongoing']+=value;group['ongoing_modules'].append({'id':key,'name':first['name'],'credits':value})
        for r in bucket:
            if r['course'] is not None:r['course']['count_reason']='counted' if len(bucket)==1 else 'merged'
    for group in groups.values():
        group['earned']=round(group['earned'],2);group['ongoing']=round(group['ongoing'],2)
    return list(groups.values())

def snapshot(store,account,data):
    state=plan(store,account)
    courses=course_list(data,state)
    statistics=progress_statistics(data,state,courses)
    rows=store.db.execute('SELECT id,payload,created,seen FROM changes WHERE account_id=? ORDER BY created DESC,rowid DESC LIMIT 500',(account,)).fetchall()
    documents=store.db.execute('SELECT id,title,term,category,language,source,length(content),created,deleted FROM documents WHERE account_id=? ORDER BY created DESC',(account,)).fetchall()
    return dict(state,effective_assignments=effective_assignments(data,state,courses),courses_view=courses,progress_stats=statistics,changes=[dict(json.loads(raw),id=key,created=created,seen=bool(seen)) for key,raw,created,seen in rows],
        unread=store.db.execute('SELECT COUNT(*) FROM changes WHERE account_id=? AND seen=0',(account,)).fetchone()[0],
        documents=[dict(zip(('id','title','term','category','language','source','size','created','deleted'),row)) for row in documents],
        modules=module_list(data),exams_view=exam_list(data,state['exams']),
        official_summaries=[g for g in data.get('grades',[]) if g.get('kind')=='program'])

def date_value(value):
    value=string(value,40)
    if not value:return ''
    try:
        d=datetime.fromisoformat(value)
        if len(value)==10:d=datetime.combine(d.date(),time(23,59,59))
        if d.tzinfo is None:d=d.replace(tzinfo=BERLIN)
        return d.astimezone(BERLIN).isoformat()
    except ValueError:raise ConsoleError('日期格式不正确。') from None

def add_document(store,account,content,title,term='',category='other',language='',source='upload'):
    if not isinstance(content,bytes) or not 0<len(content)<=MAX_PDF or not content.startswith(b'%PDF-'):raise ConsoleError('请选择 10 MB 以内的 PDF 文件。')
    title=string(title,160,True);term=string(term,80);language=string(language,20)
    if category not in ('enrolment','transcript','exams','other'):raise ConsoleError('文件分类不正确。')
    digest=hashlib.sha256(content).hexdigest()
    row=store.db.execute('SELECT id FROM documents WHERE account_id=? AND digest=?',(account,digest)).fetchone()
    if row:
        store.db.execute('UPDATE documents SET deleted=0 WHERE id=?',(row[0],));return row[0]
    count,total=store.db.execute('SELECT count(*),coalesce(sum(length(content)),0) FROM documents WHERE account_id=?',(account,)).fetchone()
    if count>=100 or total+len(content)>200*1024*1024:raise ConsoleError('证明文件夹已达容量上限（100 份 / 200 MB）。')
    key=uuid.uuid4().hex
    store.db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,0)',(key,account,title,term,category,language,source,digest,content,stamp()))
    return key

def mutate(store,account,payload):
    action=payload['action']
    if action=='courses-batch':
        initial=plan(store,account)
        if payload.get('revision')!=initial['revision']:raise ConsoleError('其他页面已修改，请刷新后重试。',409)
        ids=payload.get('course_ids');purpose=payload.get('purpose')
        if not isinstance(ids,list) or not 1<=len(ids)<=200 or any(not isinstance(k,str) or len(k)>64 for k in ids) or len(set(ids))!=len(ids) or purpose not in ('exam','interest','exercise','exercise_credit','exercise_nocredit','undecided'):raise ConsoleError('批量分类参数不正确。')
        data=store.read(account)
        source={r['id']:r for r in course_list(data,initial)}
        initial['assignments']=effective_assignments(data,initial,list(source.values()))
        if any(k not in source for k in ids):raise ConsoleError('课程列表已更新，请刷新。',409)
        for key in ids:
            row=source[key];choice=dict(initial['course_choices'].get(key,{}))
            choice.update(will_exam=True if purpose=='exam' else None if purpose=='undecided' else False,exercise=purpose in ('exercise','exercise_credit','exercise_nocredit'),exercise_credits=purpose=='exercise_credit')
            choice.setdefault('source_snapshot',{k:row.get(k) for k in ('id','name','number','semester','status','kind','credit_value','module_number','source','active','confirmed_enrollment')})
            initial['course_choices'][key]=choice
        initial['revision']+=1
        with store.db:store.db.execute('INSERT OR REPLACE INTO workspace VALUES (?,?)',(account,json.dumps(initial,ensure_ascii=False)))
        return
    if action=='changes-read':
        if payload.get('through_id'):
            row=store.db.execute('SELECT rowid FROM changes WHERE id=? AND account_id=?',(string(payload['through_id'],64,True),account)).fetchone()
            if not row:raise ConsoleError('变化记录已更新，请刷新。',409)
            with store.db:store.db.execute('UPDATE changes SET seen=1 WHERE account_id=? AND rowid<=?',(account,row[0]))
            return
        keys=payload.get('ids')
        if not isinstance(keys,list) or len(keys)>2000 or any(not isinstance(k,str) for k in keys):raise ConsoleError('变化记录格式不正确。')
        with store.db:store.db.executemany('UPDATE changes SET seen=1 WHERE id=? AND account_id=?',[(k,account) for k in keys])
        return
    if action=='document-upload':
        try:content=base64.b64decode(payload.get('content',''),validate=True)
        except (ValueError,TypeError):raise ConsoleError('文件编码不正确。') from None
        with store.db:add_document(store,account,content,payload.get('title',''),payload.get('term',''),payload.get('category','other'),payload.get('language',''))
        return
    if action in ('document-trash','document-restore','document-edit'):
        key=string(payload.get('document_id'),64,True)
        if not store.db.execute('SELECT 1 FROM documents WHERE id=? AND account_id=?',(key,account)).fetchone():raise ConsoleError('文件不存在。',404)
        with store.db:
            if action=='document-edit':
                store.db.execute('UPDATE documents SET title=?,term=? WHERE id=? AND account_id=?',(string(payload.get('title'),160,True),string(payload.get('term',''),80),key,account))
            else:store.db.execute('UPDATE documents SET deleted=? WHERE id=? AND account_id=?',(int(action=='document-trash'),key,account))
        return
    current=plan(store,account)
    if payload.get('revision')!=current['revision']:raise ConsoleError('其他页面已修改，请刷新后重试。',409)
    if action=='course-save':
        data=store.read(account)
        key=string(payload.get('course_id'),64,True)
        source=next((c for c in course_list(data,current) if c['id']==key),None)
        if source is None:raise ConsoleError('课程不存在，请刷新报名列表。',404)
        will_exam=payload.get('will_exam')
        if will_exam is not None and type(will_exam) is not bool:raise ConsoleError('请选择考试意向。')
        group=string(payload.get('group',''),64)
        if group and group not in {g['id'] for g in current['groups']}:raise ConsoleError('课程分组不存在。')
        module_id=string(payload.get('module_id',''),80)
        valid={m['id'] for m in module_list(data)}|{'planned:'+p['id'] for p in current['planned']}
        if module_id and module_id!='none' and module_id not in valid:raise ConsoleError('对应模块不存在。')
        value=payload.get('credits')
        if value is not None:value=number(value,60)
        if type(payload.get('credits_auto',False)) is not bool:raise ConsoleError('学分来源不正确。')
        if payload.get('credits_auto'):value=None
        for field in ('ongoing','confirmed','exercise','exercise_credits'):
            if type(payload.get(field,True)) is not bool:raise ConsoleError('课程状态不正确。')
        original={k:source.get(k) for k in ('id','name','number','semester','status','kind','credit_value','module_number','source','active','confirmed_enrollment')}
        linked=next((m for m in module_list(data) if m['id']==module_id),None)
        if not module_id:linked=course_module(source,module_list(data))[0]
        if linked and group and credit_intent(payload):current['assignments'].setdefault(linked['id'],group)
        current['course_choices'][key]={'exercise_credits':bool(payload.get('exercise') and payload.get('exercise_credits',False)),'exercise':payload.get('exercise',False),'will_exam':will_exam,'group':group,'credits_auto':bool(payload.get('credits_auto') or value is None),'credits':value,'module_id':module_id,'ongoing':payload.get('ongoing',True),'confirmed':payload.get('confirmed',False),'source_snapshot':original}
    elif action=='plan-save':
        groups=payload.get('groups');assignments=payload.get('assignments');planned=payload.get('planned')
        if not isinstance(groups,list) or len(groups)>40 or not isinstance(assignments,dict) or len(assignments)>1000 or not isinstance(planned,list) or len(planned)>200:raise ConsoleError('规划格式或数量不正确。')
        ids=set();clean=[]
        for group in groups:
            if not isinstance(group,dict):raise ConsoleError('分组格式不正确。')
            if group.get('kind','required') not in ('required','elective','other'):raise ConsoleError('分组类型不正确。')
            key=string(group.get('id'),64,True)
            if key in ids:raise ConsoleError('分组标识重复。')
            ids.add(key);clean.append({'id':key,'name':string(group.get('name'),100,True),'target':number(group.get('target')),'kind':string(group.get('kind','required'),30)})
        if any(not isinstance(key,str) or value not in ids for key,value in assignments.items()):raise ConsoleError('模块分组不存在。')
        clean_planned=[];planned_ids=set()
        for row in planned:
            if not isinstance(row,dict) or row.get('status','planned') not in ('planned','ongoing'):raise ConsoleError('待修模块格式不正确。')
            if row.get('group') not in ids:raise ConsoleError('规划模块分组不存在。')
            planned_id=string(row.get('id'),64,True)
            if planned_id in planned_ids:raise ConsoleError('待修模块标识重复。')
            planned_ids.add(planned_id)
            if row.get('will_exam') is not None and type(row.get('will_exam')) is not bool:raise ConsoleError('请选择考试意向。')
            if type(row.get('exercise',False)) is not bool or type(row.get('exercise_credits',False)) is not bool:raise ConsoleError('课程用途不正确。')
            module_id=string(row.get('module_id',''),80)
            if module_id and module_id not in {m['id'] for m in module_list(store.read(account))}:raise ConsoleError('对应的成绩模块不存在。')
            clean_planned.append({'exercise_credits':bool(row.get('exercise') and row.get('exercise_credits',False)),'exercise':row.get('exercise',False),'will_exam':row.get('will_exam'),'module_id':module_id,'id':planned_id,'name':string(row.get('name'),160,True),'credits':number(row.get('credits'),60),'group':row['group'],'semester':string(row.get('semester',''),80),'status':string(row.get('status','planned'),30)})
        removed={p['id']:p for p in current['planned'] if p['id'] not in planned_ids}
        for choice in current.get('course_choices',{}).values():
            link=choice.get('module_id','')
            if link.startswith('planned:') and link[8:] in removed:
                official=removed[link[8:]].get('module_id','')
                choice['module_id']=official or 'missing:'+link[8:]
        old_rows=course_list(store.read(account),current)
        old_effective=effective_assignments(store.read(account),current,old_rows)
        old_plans={p['id']:p for p in current['planned']}
        for row in old_rows:
            link=row.get('module_id','')
            if link.startswith('planned:'):link=old_plans.get(link[8:],{}).get('module_id','')
            if link in old_effective and row['id'] in current.get('course_choices',{}):
                current['course_choices'][row['id']]['group']=assignments.get(link,'')
        current.update(groups=clean,assignments=assignments,planned=clean_planned)
    elif action in ('exam-save','exam-delete'):
        key=payload.get('exam_id') or uuid.uuid4().hex
        current['exams']=[e for e in current['exams'] if e['id']!=key]
        if action=='exam-save':
            if len(current['exams'])>=100:raise ConsoleError('个人考试计划最多 100 条。')
            current['exams'].append({'id':string(key,64,True),'title':string(payload.get('title'),160,True),'number':string(payload.get('number',''),80),'program':string(payload.get('program',''),160),'start':date_value(payload.get('start','')),'room':string(payload.get('room',''),160),'registration_deadline':date_value(payload.get('registration_deadline','')),'withdrawal_deadline':date_value(payload.get('withdrawal_deadline','')),'status':string(payload.get('status','待确认'),80),'source':'personal','note':string(payload.get('note',''),2000)})
    else:raise ConsoleError('不支持的工作区操作。')
    current['revision']+=1
    with store.db:store.db.execute('INSERT OR REPLACE INTO workspace VALUES (?,?)',(account,json.dumps(current,ensure_ascii=False)))

def safe_pdf_url(value):
    try:
        p=urlsplit(value)
        return p.scheme=='https' and p.hostname=='www.campo.fau.de' and p.port in (None,443) and not p.username and not p.password and not p.fragment and p.path.startswith('/qisserver/')
    except ValueError:return False

PDF_LINKS = r'''(() => Array.from(document.querySelectorAll('a[href]')).map(a=>({url:a.href,title:(a.innerText||a.title||a.getAttribute('aria-label')||'').trim()})).filter(a=>a.title && /\.pdf(?:[?#]|$)|\/report(?:ing)?\/|reportFile|downloadReport/i.test(a.url)).slice(0,30))()'''

def fetch_pdf(url,cookies):
    import requests
    if not safe_pdf_url(url):raise DataError('证明下载地址不符合 Campo 官方地址。')
    with requests.get(url,cookies=cookies,allow_redirects=False,stream=True,timeout=(10,20)) as r:
        if r.status_code!=200:raise DataError('证明下载未成功。')
        if int(r.headers.get('Content-Length','0') or 0)>MAX_PDF:raise DataError('证明文件超过 10 MB。')
        result=bytearray()
        for chunk in r.iter_content(65536):
            if len(result)+len(chunk)>MAX_PDF:raise DataError('证明文件超过 10 MB。')
            result.extend(chunk)
        if not result.startswith(b'%PDF-'):raise DataError('官方返回的不是 PDF。')
        return bytes(result)

def capture_documents(page,context):
    links=page.evaluate(PDF_LINKS)
    if not isinstance(links,list):raise DataError('证明入口尚未适配。')
    safe=[link for link in links if isinstance(link,dict) and safe_pdf_url(link.get('url',''))]
    cookies={c['name']:c['value'] for c in context.cookies('https://www.campo.fau.de')}
    result=[];failed=0
    for link in safe[:12]:
        try:
            content=fetch_pdf(link['url'],cookies)
            result.append({'content':content,'title':str(link['title'])[:160] or 'Campo 证明','category':'transcript' if re.search('noten|transcript|grade',link['title'],re.I) else 'exams' if re.search('prüfung|exam',link['title'],re.I) else 'other'})
        except Exception:failed+=1
    return result,{'checked_at':stamp(),'found':len(safe),'saved':len(result),'failed':failed,'message':'已读取直接 PDF 入口；需表单生成的证明请从官方站点下载后导入。' if safe else '未找到可直接下载的 PDF 入口。可从官方站点下载后导入。'}
