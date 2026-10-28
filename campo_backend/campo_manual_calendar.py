"""Personal timetable rules, kept separate from school sync and credit calculations."""
from datetime import date, datetime, timedelta, timezone
import re
import uuid
from .console import ConsoleError
from .campo_source.core import BERLIN


def text(value, limit, required=False):
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        raise ConsoleError('请填写有效的课程名称、地点或备注。')
    return value.strip()


def day(value):
    try:
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
        result=date.fromisoformat(value)
        if not 2000<=result.year<=2100:raise ValueError()
        return result
    except (ValueError,TypeError):raise ConsoleError('日期需要在 2000–2100 年之间。') from None


def clock(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ConsoleError('请填写有效的上课时间。')
    return value


def local(day_value, time_value):
    naive=datetime.fromisoformat(day_value+'T'+time_value)
    aware=naive.replace(tzinfo=BERLIN)
    if aware.astimezone(timezone.utc).astimezone(BERLIN).replace(tzinfo=None)!=naive:
        raise ConsoleError(f'{day_value} {time_value} 因德国夏令时切换不存在，请调整时间。')
    return aware.isoformat()


def fields(payload):
    result={'title':text(payload.get('title'),160,True),'room':text(payload.get('room',''),160),'description':text(payload.get('description',''),2000),'date':day(payload.get('date')).isoformat(),'start_time':clock(payload.get('start_time')),'end_time':clock(payload.get('end_time'))}
    if result['end_time']<=result['start_time']:raise ConsoleError('结束时间必须晚于开始时间；跨夜课程请分成两节添加。')
    local(result['date'],result['start_time']);local(result['date'],result['end_time'])
    return result


def dates(rule):
    first=day(rule['date'])
    if rule['repeat']=='none':return [first.isoformat()]
    end=day(rule['until']);anchor=first-timedelta(days=first.weekday());result=[];current=first
    while current<=end:
        if current.weekday() in rule['weekdays'] and ((current-anchor).days//7)%rule['interval']==0:result.append(current.isoformat())
        current+=timedelta(days=1)
    return result


def events(rules):
    result=[]
    for rule in rules:
        for occurrence in dates(rule):
            override=rule.get('exceptions',{}).get(occurrence,'original')
            if override is None:continue
            value=rule if override=='original' else override
            result.append({'uid':'manual:'+rule['id']+':'+occurrence,'manual_id':rule['id'],'occurrence':occurrence,'source':'manual','repeating':rule['repeat']=='weekly','title':value['title'],'room':value['room'],'description':value['description'],'start':local(value['date'] if override!='original' else occurrence,value['start_time']),'end':local(value['date'] if override!='original' else occurrence,value['end_time']),'all_day':False})
    return sorted(result,key=lambda e:(e['start'],e['uid']))


def mutate(state,payload):
    rules=state.setdefault('manual_lessons',[]);key=payload.get('lesson_id');action=payload['action'];scope=payload.get('scope','series')
    if scope not in ('series','single'):raise ConsoleError('请选择修改这一节或整组课程。')
    existing=next((r for r in rules if r['id']==key),None) if key else None
    if key and existing is None:raise ConsoleError('手动课程不存在，请刷新后重试。',404)
    if action=='lesson-delete' and not existing:raise ConsoleError('课程不存在。',404)
    if scope=='single':
        if not existing:raise ConsoleError('请先选择一节课程。')
        occurrence=day(payload.get('occurrence')).isoformat()
        if occurrence not in dates(existing):raise ConsoleError('该节课程不属于这个重复计划。',409)
        existing.setdefault('exceptions',{})[occurrence]=None if action=='lesson-delete' else fields(payload)
        return
    if action=='lesson-delete':state['manual_lessons']=[r for r in rules if r['id']!=key];return
    value=fields(payload);repeat=payload.get('repeat','none')
    if repeat not in ('none','weekly'):raise ConsoleError('不支持的重复方式。')
    value.update(id=key or uuid.uuid4().hex,repeat=repeat,exceptions={})
    if repeat=='weekly':
        interval=payload.get('interval');weekdays=payload.get('weekdays');until=day(payload.get('until'))
        if type(interval) is not int or not 1<=interval<=8:raise ConsoleError('重复间隔需要为 1–8 周。')
        if not isinstance(weekdays,list) or not weekdays or len(weekdays)>7 or any(type(d) is not int or d not in range(7) for d in weekdays):raise ConsoleError('请至少选择一个上课星期。')
        if not 0<=(until-day(value['date'])).days<=366:raise ConsoleError('截止日期应在开始日期之后，最长一年。')
        value.update(interval=interval,weekdays=sorted(set(weekdays)),until=until.isoformat())
        if not dates(value):raise ConsoleError('所选日期和星期没有生成课程，请检查重复设置。')
    # Validate every generated date (including spring DST gaps) before replacing a rule.
    events([value])
    if not existing and len(rules)>=100:raise ConsoleError('最多保留 100 个手动课程计划，请清理旧计划。')
    state['manual_lessons']=[r for r in rules if r['id']!=key]+[value]
