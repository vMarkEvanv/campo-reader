import tempfile
import unittest
from pathlib import Path
from campo_backend.campo import Campo
from campo_backend.console import ConsoleError

class ManualCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Campo(Path(self.tmp.name));self.account=self.app.action('alice',{'action':'add','label':'Test'})['account']
    def save(self,**kw):
        state=self.app.snapshot('alice',self.account)
        payload=dict(action='lesson-save',id=self.account,revision=state['workspace']['revision'],title='Analysis',date='2026-10-19',start_time='09:00',end_time='10:30',room='Hall',repeat='none')
        payload.update(kw);return self.app.action('alice',payload)
    def test_single_persistent_account_scoped_and_not_registered(self):
        result=self.save();self.assertEqual(len(result['workspace']['manual_events']),1);self.assertEqual(result['workspace']['courses_view'],[]);self.assertEqual(result['data'].get('events',[]),[])
        other=self.app.action('alice',{'action':'add','label':'Other'})['account'];self.assertEqual(self.app.snapshot('alice',other)['workspace']['manual_events'],[])
        reopened=Campo(Path(self.tmp.name));self.assertEqual(len(reopened.snapshot('alice',self.account)['workspace']['manual_events']),1)
    def test_weekly_multiple_days_interval_inclusive_and_dst(self):
        result=self.save(repeat='weekly',weekdays=[0,2],interval=2,until='2026-11-02')['workspace'];rows=result['manual_events']
        self.assertEqual([r['occurrence'] for r in rows],['2026-10-19','2026-10-21','2026-11-02']);self.assertTrue(rows[0]['start'].endswith('+02:00'));self.assertTrue(rows[-1]['start'].endswith('+01:00'))
    def test_reschedule_cancel_and_series_delete(self):
        w=self.save(repeat='weekly',weekdays=[0],interval=1,until='2026-11-02')['workspace'];key=w['manual_lessons'][0]['id']
        w=self.save(lesson_id=key,scope='single',occurrence='2026-10-26',date='2026-10-27',start_time='11:00',end_time='12:00')['workspace']
        self.assertEqual(len(w['manual_events']),3);self.assertEqual(w['manual_events'][1]['start'][:16],'2026-10-27T11:00')
        result=self.app.action('alice',dict(action='lesson-delete',id=self.account,revision=w['revision'],lesson_id=key,scope='single',occurrence='2026-11-02'));self.assertEqual(len(result['workspace']['manual_events']),2)
        result=self.app.action('alice',dict(action='lesson-delete',id=self.account,revision=result['workspace']['revision'],lesson_id=key,scope='series'));self.assertEqual(result['workspace']['manual_events'],[])
    def test_sync_keeps_manual_separate(self):
        self.save();store=self.app.store('alice');store.save(self.account,{'identity':'Alice','fingerprint':'synthetic-alice','events':[{'uid':'official','title':'School','start':'2026-10-19T09:00:00+02:00','end':'2026-10-19T11:00:00+02:00'}]});store.close()
        snapshot=self.app.snapshot('alice',self.account);self.assertEqual(len(snapshot['data']['events']),1);self.assertEqual(len(snapshot['workspace']['manual_events']),1)
    def test_revision_invalid_inputs_atomic(self):
        self.save()
        with self.assertRaises(ConsoleError) as error:self.save(revision=0)
        self.assertEqual(error.exception.status,409)
        for changes in [dict(end_time='08:00'),dict(repeat='daily'),dict(repeat='weekly',weekdays=[],interval=1,until='2026-11-01'),dict(repeat='weekly',weekdays=[True],interval=1,until='2026-11-01'),dict(repeat='weekly',weekdays=[1],interval=0,until='2026-11-01'),dict(repeat='weekly',weekdays=[1],interval=1,until='2028-01-01'),dict(scope='single',lesson_id='missing',occurrence='2026-10-19'),dict(date='2026-02-30'),dict(date='2027-03-28',start_time='02:30',end_time='03:30')]:
            with self.subTest(changes=changes),self.assertRaises(ConsoleError):self.save(**changes)
        self.assertEqual(len(self.app.snapshot('alice',self.account)['workspace']['manual_lessons']),1)
    def test_series_edit_resets_exceptions_foreign_key_rejected(self):
        w=self.save(repeat='weekly',weekdays=[0],interval=1,until='2026-11-02')['workspace'];key=w['manual_lessons'][0]['id']
        self.save(lesson_id=key,scope='single',occurrence='2026-10-26',date='2026-10-27')
        w=self.save(lesson_id=key,repeat='weekly',weekdays=[0],interval=1,until='2026-11-02')['workspace'];self.assertEqual(w['manual_lessons'][0]['exceptions'],{})
        other=self.app.action('alice',{'action':'add','label':'Other'})['account']
        with self.assertRaises(ConsoleError):self.save(id=other,lesson_id=key,revision=0)
if __name__=='__main__':unittest.main()
