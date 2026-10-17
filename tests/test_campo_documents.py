import unittest
from unittest.mock import MagicMock,patch
from campo_backend import campo_documents as d
from campo_backend.campo_source.core import DataError
from campo_backend.campo_source import scripts

class DocumentsTests(unittest.TestCase):
    def test_navigation_follows_home_documents_then_documents_tab(self):
        page=MagicMock();phase=[0]
        home={'id':'home-doc','label':'Bescheinigungen / Documents','href':'https://www.campo.fau.de/qisserver/service.xhtml','visible':True}
        tab={'id':'documents-tab','label':'Documents','href':'','role':'tab','visible':True}
        report={'id':'report-01','label':'Certificate of enrollment','href':'https://www.campo.fau.de/qisserver/docs.xhtml#','pdf':True}
        def evaluate(script):
            if script==scripts.STATE:return {'logged_in':True,'identity':'Alice'}
            if script==d.NAVIGATION:return [home] if phase[0]==0 else [tab]
            if script==d.INDEX:return [report] if phase[0]==2 else []
            raise AssertionError('unexpected script')
        page.evaluate.side_effect=evaluate
        def activate(p,item):phase[0]=1 if item['id']=='home-doc' else 2
        with patch.object(d,'activate',side_effect=activate):index=d.discover(page,'Alice')
        self.assertEqual(index[0]['title'],'Certificate of enrollment')
        self.assertEqual(index[0]['category'],'enrolment')

    def test_fragment_tabs_and_jsf_actions_click_instead_of_navigating(self):
        for item in [dict(id='tab',href='https://www.campo.fau.de/qisserver/service.xhtml#documents',role='tab'),dict(id='menu',href='https://www.campo.fau.de/qisserver/service.xhtml',action=True)]:
            page=MagicMock();d.activate(page,item)
            page.goto.assert_not_called();page.locator.return_value.first.click.assert_called_once()

    def test_catalog_does_not_expose_urls_or_download_without_selection(self):
        page=MagicMock();context=MagicMock()
        rows=[{'key':'a'*24,'title':'Certificate','category':'enrolment','language':'en','href':'https://www.campo.fau.de/qisserver/report?secret=private'}]
        with patch.object(d,'discover',return_value=rows),patch.object(d,'fetch_pdf') as fetch:
            documents,info=d.collect(page,context,'Alice')
        self.assertEqual(documents,[]);fetch.assert_not_called()
        self.assertNotIn('private',str(info));self.assertNotIn('href',info['catalog'][0])

    def test_only_selected_document_is_retrieved_and_identity_checked(self):
        page=MagicMock();context=MagicMock();context.cookies.return_value=[]
        row={'key':'a'*24,'title':'Certificate','category':'enrolment','language':'en','href':'https://www.campo.fau.de/qisserver/enrollment.pdf'}
        page.evaluate.return_value={'logged_in':True,'identity':'Alice'}
        with patch.object(d,'discover',return_value=[row]),patch.object(d,'fetch_pdf',return_value=b'%PDF-1.4\n%%EOF') as fetch:
            documents,info=d.collect(page,context,'Alice','a'*24)
        fetch.assert_called_once();self.assertEqual(documents[0]['content'],b'%PDF-1.4\n%%EOF')
        self.assertEqual(documents[0]['language'],'en')
        page.evaluate.return_value={'logged_in':True,'identity':'Bob'}
        with patch.object(d,'discover',return_value=[row]),patch.object(d,'fetch_pdf') as fetch:
            with self.assertRaises(DataError):d.collect(page,context,'Alice','a'*24)
        fetch.assert_not_called()

    def test_missing_document_is_not_replaced_by_another_report(self):
        with patch.object(d,'discover',return_value=[]),patch.object(d,'fetch_pdf') as fetch:
            with self.assertRaises(DataError):d.collect(MagicMock(),MagicMock(),'Alice','b'*24)
        fetch.assert_not_called()

    def test_report_semester_selection_and_explicit_create_pdf(self):
        page=MagicMock()
        options=[{'id':'studyserviceForm:report:settings:setting_input','options':[{'label':'Wintersemester 2026/27','value':'20262','selected':False},{'label':'Sommersemester 2026','value':'20261','selected':False}]}]
        with patch.object(d,'semester_options',return_value=options):
            term=d.configure_report(page,'Sommersemester 2026')
        self.assertEqual(term,'Sommersemester 2026')
        self.assertTrue(any(call.kwargs=={'value':'20261'} for call in page.locator.return_value.select_option.call_args_list))
        page.locator.return_value.click.assert_called_once()
        page=MagicMock()
        with patch.object(d,'semester_options',return_value=options):
            self.assertEqual(d.configure_report(page),'Wintersemester 2026/27')
        with patch.object(d,'semester_options',return_value=options):
            with self.assertRaises(DataError):d.configure_report(page,'Wintersemester 2020/21')
