"""Verify real stage commits while another collector is deliberately blocked."""
import tempfile,threading,time,unittest,json
from pathlib import Path
from unittest.mock import MagicMock,patch
from campo_backend.campo import Campo
from campo_backend.campo_source import scripts
from campo_backend.campo_source.core import calendar_fingerprint,DataError

class StagedSyncTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.c=Campo(Path(self.temp.name));self.user='test';self.c.public_user=self.user
  self.a=self.c.action(self.user,{'action':'add','label':'A'})['account']
  self.url='https://www.campo.fau.de/qisserver/pages/cm/exa/timetable/individualTimetableCalendarExport.faces?user=fixture&hash=fixture'
  self.binding={'identity':'Fixture','fingerprint':calendar_fingerprint(self.url)}
  self.c.commit_sync(self.user,self.a,dict(self.binding,events=[{'title':'old'}],grades=[{'name':'old grade'}]),'subscription','session')
 def snapshot(self):return self.c.snapshot(self.user,self.a)
 def run_blocked(self,blocked,fail=False):
  entered,release=threading.Event(),threading.Event();errors=[]
  pw=MagicMock();context=pw.chromium.launch.return_value.new_context.return_value
  context.storage_state.return_value={'cookies':[],'origins':[]}
  context.new_page.return_value.evaluate.side_effect=lambda source:dict(logged_in=True,identity='Fixture',calendar_url=self.url,semester='WS 2026') if source==scripts.STATE else True
  def calendar(url):
   if blocked=='calendar':entered.set();release.wait(8)
   if fail:raise DataError('calendar failed')
   return {'events':[{'title':'fresh calendar'}]}
  def grades(page):
   if blocked=='grades':entered.set();release.wait(8)
   return [{'name':'fresh grades'}]
  def work():
   try:self.c.sync(self.user,self.a,'user','password')
   except BaseException as exc:errors.append(exc)
  self.c.slots.acquire();self.c.jobs[(self.user,self.a)]={'running':True}
  with patch('campo_backend.browser.sync_playwright') as factory,patch('campo_backend.campo.launch_browser',return_value=pw.chromium.launch.return_value),patch.object(self.c,'calendar',side_effect=calendar),patch.object(self.c,'read_grades',side_effect=grades),patch('campo_backend.campo.campo_courses.collect',side_effect=DataError('courses unavailable')),patch('campo_backend.campo.campo_planner.collect',side_effect=DataError('planner unavailable')),patch('campo_backend.campo.campo_documents.collect',side_effect=DataError('documents unavailable')):
   factory.return_value.__enter__.return_value=pw
   t=threading.Thread(target=work);t.start()
   try:
    self.assertTrue(entered.wait(3))
    expected='grades' if blocked=='calendar' else 'events';name='fresh grades' if expected=='grades' else 'fresh calendar';field='name' if expected=='grades' else 'title'
    end=time.monotonic()+3
    while self.snapshot()['data'].get(expected,[{}])[0].get(field)!=name and time.monotonic()<end:time.sleep(.02)
    s=self.snapshot();self.assertEqual(s['data'][expected][0][field],name)
    self.assertTrue(s['job']['running'],'Other collector must still be blocked')
    self.assertEqual(s['job']['data_revision'],s['data']['sync_revision'])
    with self.c.lock, patch('campo_backend.campo.workspace.snapshot',side_effect=AssertionError('light poll rebuilt workspace')):
     s_revision=self.c.jobs[(self.user,self.a)]['data_revision']
     light=self.c.snapshot(self.user,self.a,lightweight=True)
     self.assertEqual(light['job']['data_revision'],s_revision)
   finally:release.set();t.join(5)
   self.assertFalse(t.is_alive());self.assertFalse(errors,errors)
 def test_calendar_visible_before_slow_grades(self):self.run_blocked('grades')
 def test_grades_visible_before_slow_calendar(self):self.run_blocked('calendar')
 def test_calendar_failure_does_not_discard_grades(self):
  self.run_blocked('calendar',fail=True)
  s=self.snapshot();self.assertEqual(s['data']['events'],[{'title':'old'}]);self.assertEqual(s['data']['grades'],[{'name':'fresh grades'}]);self.assertIn('课表',s['job']['message'])
 def test_stage_merge_and_identity_binding(self):
  self.c.commit_sync(self.user,self.a,dict(self.binding,grades=[{'name':'fresh'}]),None,None)
  self.c.commit_sync(self.user,self.a,dict(self.binding,events=[]),None,None)
  self.assertEqual(self.snapshot()['data']['grades'],[{'name':'fresh'}]);self.assertEqual(self.snapshot()['data']['events'],[])
  old=self.snapshot()['data']
  with self.assertRaises(DataError):self.c.commit_sync(self.user,self.a,dict(identity='Other',fingerprint='different',events=[]),None,None)
  self.assertEqual(self.snapshot()['data'],old)
