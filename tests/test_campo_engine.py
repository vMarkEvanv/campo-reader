import tempfile
import json
import sqlite3
import base64
from campo_backend.campo_source import scripts
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock
from campo_backend.campo import Campo, SessionExpired
from campo_backend.console import ConsoleError
from campo_backend.campo_source.core import DataError, parse_calendar, calendar_fingerprint, validate_grades

class CampoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.campo=Campo(Path(self.tmp.name))

    def test_private_accounts_and_bound_identity(self):
        a=self.campo.action('alice',{'action':'add','label':'A'})['account']
        self.assertEqual(self.campo.snapshot('bob')['accounts'],[])
        with self.assertRaises(ConsoleError):self.campo.snapshot('bob',a)
        store=self.campo.store('alice')
        store.save(a,{'identity':'Alice','fingerprint':'alice','grades':[]})
        with self.assertRaises(DataError):store.save(a,{'identity':'Bob','fingerprint':'bob','grades':[]})
        store.close()
        self.assertNotIn('fingerprint',self.campo.snapshot('alice',a)['data'])
        self.campo.action('alice',{'action':'delete','id':a})
        self.assertEqual(self.campo.snapshot('alice')['accounts'],[])

    def test_failed_sync_preserves_cache_and_no_password_saved(self):
        a=self.campo.action('alice',{'action':'add','label':'A'})['account']
        store=self.campo.store('alice');store.save(a,{'identity':'Alice','fingerprint':'alice','grades':[{'name':'Math'}]});store.close()
        self.campo.slots.acquire(); self.campo.jobs[('alice',a)]={'running':True,'message':''}
        with patch('playwright.sync_api.sync_playwright',side_effect=RuntimeError('secret-password')):
            self.campo.sync('alice',a,'username','secret-password')
        d=self.campo.snapshot('alice',a)
        self.assertEqual(d['data']['grades'],[{'name':'Math'}]);self.assertFalse(d['job']['running'])
        self.assertNotIn('secret-password',str(d))
        for path in self.campo.root.iterdir():self.assertNotIn(b'secret-password',path.read_bytes())
        self.assertTrue(self.campo.slots.acquire(blocking=False))

    def test_calendar_validation_and_dst(self):
        url='https://www.campo.fau.de/qisserver/pages/cm/exa/timetable/individualTimetableCalendarExport.faces?user=alice&hash=secret'
        self.assertEqual(calendar_fingerprint(url),calendar_fingerprint(url.replace('secret','new')))
        with self.assertRaises(DataError):calendar_fingerprint(url.replace('www.campo.fau.de','example.com'))
        data=b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:test\r\nDTSTART;TZID=Europe/Berlin:20261019T081500\r\nDTEND;TZID=Europe/Berlin:20261019T094500\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Math\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        events=parse_calendar(data,date(2026,10,1),date(2026,12,1))
        self.assertEqual(len(events),3);self.assertTrue(events[0]['start'].endswith('+02:00'));self.assertTrue(events[1]['start'].endswith('+01:00'))
        with self.assertRaises(DataError):validate_grades({'table_found':True,'columns_ok':True,'collapsed':1,'rows':[]})

class CampoRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.campo=Campo(Path(self.tmp.name))
        self.campo.public_user='alice'
        self.account=self.campo.action('alice',{'action':'add','label':'A'})['account']
        self.url='https://www.campo.fau.de/qisserver/pages/cm/exa/timetable/individualTimetableCalendarExport.faces?user=alice&hash=secret-calendar-token'
        store=self.campo.store('alice')
        store.save(self.account,{'identity':'Alice','fingerprint':calendar_fingerprint(self.url),'grades':[{'name':'Math','grade':'1.0'}],'events':[{'title':'old'}]})
        settings=self.campo.preferences(store,self.account)
        self.session={'cookies':[{'name':'JSESSIONID','value':'private-session-cookie','domain':'www.campo.fau.de','path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax'}],'origins':[]}
        settings.update(subscription=self.campo.cipher.encrypt(self.url.encode()).decode(),session=self.campo.cipher.encrypt(json.dumps(self.session).encode()).decode(),last_attempt=1000)
        self.campo.save_preferences(store,self.account,settings);store.close()

    def test_default_settings_persistence_and_token_confidentiality(self):
        d=self.campo.snapshot('alice',self.account)
        self.assertEqual(d['settings']['interval_minutes'],10)
        self.assertTrue(d['settings']['enabled']);self.assertTrue(d['settings']['ready'])
        self.assertNotIn('secret-calendar-token',str(d));self.assertNotIn('subscription',d['settings']);self.assertNotIn('session',d['settings']);self.assertNotIn('private-session-cookie',str(d))
        self.campo.action('alice',{'action':'settings','id':self.account,'interval_minutes':30,'enabled':False})
        reopened=Campo(Path(self.tmp.name))
        d=reopened.snapshot('alice',self.account)
        self.assertEqual(d['settings']['interval_minutes'],30);self.assertFalse(d['settings']['enabled'])
        for path in self.campo.root.iterdir():
            self.assertNotIn(b'secret-calendar-token',path.read_bytes());self.assertNotIn(b'private-session-cookie',path.read_bytes())
        for minutes in [0,1441,True,1.5,'10']:
            with self.assertRaises(ConsoleError):self.campo.action('alice',{'action':'settings','id':self.account,'interval_minutes':minutes,'enabled':True})

    def test_timer_not_early_and_no_overlapping_sync(self):
        with patch('campo_backend.campo.time.time',return_value=1599),patch('campo_backend.campo.threading.Thread') as thread:
            self.campo.tick();thread.assert_not_called()
        with patch('campo_backend.campo.time.time',return_value=1600),patch('campo_backend.campo.threading.Thread') as thread:
            self.campo.tick();self.assertEqual(thread.call_count,1)
            self.campo.tick();self.assertEqual(thread.call_count,1)
        self.campo.slots.release()

    def test_disabled_timer_does_not_download(self):
        self.campo.action('alice',{'action':'settings','id':self.account,'interval_minutes':10,'enabled':False})
        with patch('campo_backend.campo.threading.Thread') as thread:
            self.campo.tick();thread.assert_not_called()

    def perform_sync(self, expired=False, grades_error=False):
        self.campo.slots.acquire();self.campo.jobs[('alice',self.account)]={'running':True}
        pw=MagicMock();browser=pw.chromium.launch.return_value;context=browser.new_context.return_value
        context.storage_state.return_value=self.session
        page=context.new_page.return_value
        state={'logged_in':not expired,'identity':'Alice','calendar_url':self.url,'semester':'Winter 2026'}
        def evaluate(script):
            if script==scripts.STATE:return state
            if script==scripts.OPEN_CALENDAR:return True
            raise AssertionError('Unexpected script, including password login')
        page.evaluate.side_effect=evaluate
        with patch('playwright.sync_api.sync_playwright') as launch,patch.object(self.campo,'calendar',return_value={'events':[{'title':'new'}],'range_start':'2026-01-01','range_end':'2027-01-01'}),patch.object(self.campo,'read_grades',side_effect=DataError('Grade read failed') if grades_error else None,return_value=[{'name':'Physics','grade':'1.3'}]),patch('campo_backend.campo.campo_courses.collect',return_value=([],{'checked_at':'2026-10-17','scope':'all'})),patch('campo_backend.campo.campo_planner.collect',return_value={'checked_at':'2026-10-17','modules':[]}),patch('campo_backend.campo.campo_documents.collect',return_value=([],{'checked_at':'2026-10-17','catalog':[]})):
            launch.return_value.__enter__.return_value=pw
            self.campo.sync('alice',self.account,None,None)
        browser.new_context.assert_called_once_with(storage_state=self.session)
        return self.campo.snapshot('alice',self.account)

    def test_automatic_refresh_updates_both_without_password(self):
        result=self.perform_sync()
        self.assertEqual(result['data']['events'],[{'title':'new'}])
        self.assertEqual(result['data']['grades'],[{'name':'Physics','grade':'1.3'}])
        self.assertTrue(result['data']['calendar_updated_at']);self.assertTrue(result['data']['grades_updated_at'])
        self.assertTrue(result['settings']['ready']);self.assertFalse(result['job']['running'])
        self.assertNotIn('private-session-cookie',str(result))

    def test_expired_session_preserves_cache_and_stops_repeated_attempts(self):
        old=self.campo.snapshot('alice',self.account)['data']
        result=self.perform_sync(expired=True)
        self.assertEqual(result['data'],old);self.assertTrue(result['settings']['reauth_required']);self.assertFalse(result['settings']['ready'])
        with patch('campo_backend.campo.threading.Thread') as thread:
            self.campo.tick();thread.assert_not_called()

    def test_failed_grades_preserves_grades_but_updates_calendar(self):
        old=self.campo.snapshot('alice',self.account)['data']
        result=self.perform_sync(grades_error=True)
        self.assertEqual(result['data']['grades'],old['grades'])
        self.assertIsNone(result['data']['grades_updated_at'])
        self.assertEqual(result['data']['events'],[{'title':'new'}])
        self.assertFalse(result['job']['running'])
        self.assertIn('成绩',result['job']['message']);self.assertIn('更新未完成',result['job']['message'])
        self.assertTrue(result['settings']['ready'])

    def test_atomic_cache_and_session_commit(self):
        old=self.campo.snapshot('alice',self.account)['data']
        store=self.campo.store('alice')
        store.db.execute("CREATE TRIGGER fail_settings BEFORE INSERT ON web_settings BEGIN SELECT RAISE(ABORT, 'test write failure'); END")
        store.db.commit();store.close()
        result={'identity':'Alice','fingerprint':calendar_fingerprint(self.url),'events':[{'title':'new'}],'grades':[]}
        with self.assertRaises(sqlite3.IntegrityError):self.campo.commit_sync('alice',self.account,result,'new-token','new-session')
        self.assertEqual(self.campo.snapshot('alice',self.account)['data'],old)

    def test_session_rejects_foreign_origin(self):
        settings={'session':self.campo.cipher.encrypt(json.dumps({'cookies':[{'domain':'evil.example'}],'origins':[]}).encode()).decode()}
        with self.assertRaises(SessionExpired):self.campo.restore_session(settings)


