def check():
    from android_browser import Page,rpc
    from campo_backend.campo_source import scripts
    class Context:
        def cookies(self,url):return []
    page=Page(Context())
    page.goto("https://www.campo.fau.de/qisserver/fixture")
    import time
    deadline=time.monotonic()+15
    while True:
        state=page.evaluate(scripts.STATE)
        if state['logged_in'] and state['identity']=='Synthetic':break
        if time.monotonic()>deadline:raise AssertionError('Synthetic fixture not ready: '+repr(state))
        time.sleep(.15)
    assert page.evaluate('typeof CampoMobile')=='undefined'
    assert page.locator('#click').is_visible()
    page.locator('#click').click()
    assert page.evaluate('document.body.dataset.clicked')=='yes'
    page.locator('#term').select_option('b')
    assert page.evaluate('document.querySelector("#term").value')=='b'
    assert isinstance(rpc('cookies'),list)
    from campo_backend.campo_documents import discover
    rows=discover(page,'Synthetic')
    assert len(rows)==1 and rows[0]['category']=='enrolment'
    return 'passed'

_stage=None
def begin_stage_test():
    global _stage
    import android_runtime
    c=android_runtime._server.campo;u=c.public_user
    a=c.action(u,{'action':'add','label':'Staged fixture'})['account']
    binding={'identity':'Staged fixture','fingerprint':'staged-fixture'}
    c.commit_sync(u,a,dict(binding,events=[],grades=[]),None,None)
    c.jobs[(u,a)]={'running':True,'message':'正在读取成绩…'}
    _stage=(c,u,a,binding)
    return a

def publish_stage_test():
    from datetime import datetime,timedelta
    from campo_backend.campo_source.core import BERLIN
    c,u,a,binding=_stage;now=datetime.now(BERLIN).replace(hour=10,minute=0,second=0,microsecond=0)
    c.commit_sync(u,a,dict(binding,calendar_updated_at=now.isoformat(),events=[{'title':'Fresh staged timetable','start':now.isoformat(),'end':(now+timedelta(hours=1)).isoformat(),'room':'R1'}]),None,None)

def finish_stage_test():
    c,u,a,binding=_stage;c.jobs[(u,a)].update(running=False,message='课表已更新；成绩更新未完成。')

def check_pdf():
    import tempfile
    from pathlib import Path
    from android_browser import Page
    class Context:pass
    with tempfile.TemporaryDirectory() as folder:
        context=Context();context.temp=folder
        page=Page(context);received=[]
        page.on('download',lambda download:received.append(Path(download.path()).read_bytes()))
        page._downloads()
        assert received==[b'%PDF-1.4\nSynthetic report\n%%EOF']
        page._downloads()
        assert len(received)==1
    return 'passed'
