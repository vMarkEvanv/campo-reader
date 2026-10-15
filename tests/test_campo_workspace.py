import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campo_backend.campo import Campo
from campo_backend import campo_workspace as w
from campo_backend.console import ConsoleError

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.campo=Campo(Path(self.tmp.name));self.user='alice'
        self.account=self.campo.action(self.user,{'action':'add','label':'A'})['account']
        self.base={'identity':'Alice','fingerprint':'alice','synced_at':'2026-10-14T12:00:00+02:00','range_start':'2026-10-01','range_end':'2026-11-01','events':[{'uid':'weekly','title':'Math','start':'2026-10-15T10:00:00+02:00','end':'2026-10-15T11:00:00+02:00','room':'A'}],'grades':[{'kind':'module','name':'Linear Algebra','number':'01','program':'CS','status':'BE','credits':'5,0','grade':'1.3'}]}
        store=self.campo.store(self.user);store.save(self.account,self.base);store.close()
    def action(self,**payload):return self.campo.action(self.user,dict(payload,id=self.account))
    def snapshot(self):return self.campo.snapshot(self.user,self.account)
    def commit(self,data):self.campo.commit_sync(self.user,self.account,data,'encrypted-subscription','encrypted-session')

    def test_baseline_identical_sync_and_window_roll_do_not_create_noise(self):
        self.assertEqual(w.change_items({},self.base),[])
        self.assertEqual(w.change_items(self.base,self.base),[])
        new=copy.deepcopy(self.base);new.update(range_start='2026-10-16',events=[])
        self.assertEqual(w.change_items(self.base,new),[])

    def test_changed_time_room_and_new_grade_and_read_watermark(self):
        new=copy.deepcopy(self.base);new['events'][0].update(start='2026-10-15T12:00:00+02:00',room='B');new['grades'][0]['grade']='1.0'
        self.commit(new);state=self.snapshot()['workspace']
        self.assertEqual(state['unread'],2)
        calendar=next(c for c in state['changes'] if c['kind']=='calendar')
        self.assertEqual(calendar['action'],'changed');self.assertEqual({f['field'] for f in calendar['fields']},{'开始时间','地点'})
        through=state['changes'][0]['id']
        next_data=copy.deepcopy(new);next_data['grades'][0]['status']='EN';self.commit(next_data)
        state=self.action(action='changes-read',through_id=through)['workspace'];self.assertEqual(state['unread'],1)
        self.assertEqual(self.campo.snapshot('bob')['accounts'],[])

    def test_sync_failure_rolls_back_change_log(self):
        store=self.campo.store(self.user);store.db.execute("CREATE TRIGGER fail_settings BEFORE INSERT ON web_settings BEGIN SELECT RAISE(ABORT, 'failure'); END");store.db.commit();store.close()
        new=copy.deepcopy(self.base);new['grades'][0]['grade']='1.0'
        with self.assertRaises(Exception):self.commit(new)
        self.assertEqual(self.snapshot()['workspace']['changes'],[])
        self.assertEqual(self.snapshot()['data']['grades'],self.base['grades'])

    def test_exams_merge_only_explicit_calendar_and_registered_grade(self):
        data=copy.deepcopy(self.base);data['grades'] += [{'kind':'exam','name':'Math exam','number':'X12','status':'AN','program':'CS'}]
        self.assertEqual(w.exam_list(data,[])[0]['start'],'')
        data['events'].append({'uid':'exam','title':'Klausur Math exam X12','start':'2026-10-25T10:00:00+01:00','room':'Hall'})
        exams=w.exam_list(data,[]);self.assertEqual(len(exams),1);self.assertEqual(exams[0]['room'],'Hall');self.assertEqual(exams[0]['withdrawal_deadline'],'')
        self.assertTrue(w.date_value('2026-10-25').endswith('23:59:59+01:00'))
        self.assertTrue(w.date_value('2026-10-15T12:30').endswith('+02:00'))

    def test_personal_exam_edit_conflict_and_delete(self):
        d=self.action(action='exam-save',revision=0,title='Test',start='2026-11-05T09:00',registration_deadline='2026-10-31')['workspace']
        self.assertEqual(d['exams_view'][0]['source'],'personal')
        with self.assertRaises(ConsoleError):self.action(action='exam-save',revision=0,title='Stale')
        key=d['exams'][0]['id'];d=self.action(action='exam-delete',revision=1,exam_id=key)['workspace'];self.assertEqual(d['exams'],[])

    def test_module_plan_never_counts_exam_or_program_rows(self):
        data=copy.deepcopy(self.base);data['grades'] += [dict(self.base['grades'][0]),{'kind':'exam','name':'Exam','credits':'5','status':'BE'},{'kind':'program','name':'CS','credits':'120'}]
        self.commit(data);state=self.snapshot()['workspace'];self.assertEqual(len(state['modules']),1);self.assertEqual(state['modules'][0]['credit_value'],5)
        key=state['modules'][0]['id']
        d=self.action(action='plan-save',revision=0,groups=[{'id':'required','name':'必修','kind':'required','target':60}],assignments={key:'required'},planned=[{'id':'future','name':'Analysis','group':'required','credits':5,'semester':'WS 2026','status':'planned'}])['workspace']
        self.assertEqual(d['groups'][0]['target'],60);self.assertEqual(d['planned'][0]['status'],'planned')
        with self.assertRaises(ConsoleError):self.action(action='plan-save',revision=0,groups=[],assignments={},planned=[])
        with self.assertRaises(ConsoleError):self.action(action='plan-save',revision=1,groups=[],assignments={key:'missing'},planned=[])

    def test_documents_dedupe_ownership_metadata_trash_restore(self):
        content=b'%PDF-1.4\nTest proof\n%%EOF';encoded=base64.b64encode(content).decode()
        payload=dict(action='document-upload',content=encoded,title='Proof',term='WS 2026',category='enrolment')
        state=self.action(**payload)['workspace'];self.action(**payload)
        key=state['documents'][0]['id'];self.assertEqual(len(self.snapshot()['workspace']['documents']),1)
        self.assertEqual(self.campo.document(self.user,self.account,key)[1],content)
        other=self.campo.action(self.user,{'action':'add','label':'B'})['account']
        with self.assertRaises(ConsoleError):self.campo.document(self.user,other,key)
        self.action(action='document-edit',document_id=key,title='New title',term='SS 2027')
        self.action(action='document-trash',document_id=key)
        with self.assertRaises(ConsoleError):self.campo.document(self.user,self.account,key)
        self.action(action='document-restore',document_id=key)
        self.assertEqual(self.campo.document(self.user,self.account,key)[0],'New title')
        with self.assertRaises(ConsoleError):self.action(action='document-upload',content=base64.b64encode(b'not PDF').decode(),title='Bad')

    def test_optional_pdf_discovery_does_not_follow_external_urls(self):
        page=type('Page',(),{'evaluate':lambda self,s:[{'title':'External','url':'https://evil.example/file.pdf'},{'title':'Proof','url':'https://www.campo.fau.de/qisserver/proof.pdf'}]})()
        context=type('Context',(),{'cookies':lambda self,url:[]})()
        with patch.object(w,'fetch_pdf',return_value=b'%PDF-1.4\n%%EOF') as fetch:
            documents,info=w.capture_documents(page,context)
        self.assertEqual(fetch.call_count,1);self.assertEqual(len(documents),1);self.assertEqual(info['found'],1)
        for url in ['http://www.campo.fau.de/qisserver/proof.pdf','https://www.campo.fau.de:444/qisserver/proof.pdf','https://evil@www.campo.fau.de/qisserver/proof.pdf']:
            self.assertFalse(w.safe_pdf_url(url))

class CourseWorkspaceTests(WorkspaceTests):
    def test_course_choices_persist_through_sync_and_revision_guard(self):
        initial=self.snapshot()['workspace'];courses=initial['courses_view'];self.assertTrue(courses)
        result=self.action(action='plan-save',revision=initial['revision'],groups=[{'id':'g','name':'Required','target':30}],assignments={},planned=[])
        payload=dict(action='course-save',revision=result['workspace']['revision'],course_id=courses[0]['id'],will_exam=True,group='g',module_id='',credits=5,ongoing=True,confirmed=True)
        result=self.action(**payload)
        self.assertEqual(result['workspace']['progress_stats'][0]['ongoing'],5)
        with self.assertRaises(ConsoleError):self.action(**payload)
        self.commit(copy.deepcopy(self.base))
        current=self.snapshot()['workspace'];self.assertEqual(current['courses_view'][0]['will_exam'],True);self.assertEqual(current['progress_stats'][0]['ongoing'],5)
        self.assertEqual(self.campo.snapshot('bob')['accounts'],[])

class CourseUpgradeTests(WorkspaceTests):
    def test_batch_revision_validation_and_persistence(self):
        initial=self.snapshot()['workspace'];key=initial['courses_view'][0]['id']
        result=self.action(action='courses-batch',revision=initial['revision'],course_ids=[key],purpose='exercise')['workspace']
        self.assertTrue(result['courses_view'][0]['exercise']);self.assertTrue(result['courses_view'][0]['classified'])
        with self.assertRaises(ConsoleError):self.action(action='courses-batch',revision=initial['revision'],course_ids=[key],purpose='interest')
        revision=result['revision']
        with self.assertRaises(ConsoleError):self.action(action='courses-batch',revision=revision,course_ids=[key,'missing'],purpose='interest')
        self.assertEqual(self.snapshot()['workspace']['revision'],revision)
    def test_plan_deletion_redirects_link_to_official_module(self):
        module=w.module_list(self.base)[0]['id']
        result=self.action(action='plan-save',revision=0,groups=[{'id':'g','name':'Required','target':30}],assignments={module:'g'},planned=[{'id':'p','name':'Plan','group':'g','credits':5,'status':'ongoing','will_exam':True,'module_id':module}])['workspace']
        key=result['courses_view'][0]['id']
        result=self.action(action='course-save',revision=result['revision'],course_id=key,group='g',will_exam=True,credits=5,module_id='planned:p',ongoing=True,confirmed=True)['workspace']
        self.assertTrue(result['courses_view'][0]['completed'])
        result=self.action(action='plan-save',revision=result['revision'],groups=result['groups'],assignments=result['assignments'],planned=[])['workspace']
        self.assertEqual(result['courses_view'][0]['module_id'],module);self.assertTrue(result['courses_view'][0]['completed']);self.assertEqual((result['progress_stats'][0]['earned'],result['progress_stats'][0]['ongoing']),(5,0))

    def test_session_expiry_is_shared_by_all_sync_entry_points(self):
        self.campo.mark_expired(self.user,self.account)
        settings=self.snapshot()['settings']
        self.assertTrue(settings['reauth_required']);self.assertFalse(settings['ready']);self.assertFalse(settings['grades_ready'])
