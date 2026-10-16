import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from campo_backend.campo import Campo
from campo_backend.campo_planner import credit_index,credit_lookup
from campo_backend.console import ConsoleError

class PerformanceTests(unittest.TestCase):
    def test_status_does_not_calculate_workspace_and_preserves_scope(self):
        with tempfile.TemporaryDirectory() as root:
            c=Campo(Path(root));a=c.action('alice',{'action':'add','label':'A'})['account']
            c.jobs[('alice',a)]={'running':True,'message':'reading'}
            with patch('campo_backend.campo.workspace.snapshot',side_effect=AssertionError('should not calculate')):
                status=c.snapshot('alice',a,lightweight=True)
                self.assertEqual(set(status),{'account','job'})
                self.assertTrue(status['job']['running'])
                with self.assertRaises(ConsoleError):c.snapshot('bob',a,lightweight=True)
    def test_internal_catalog_stays_stored_and_course_values_are_public(self):
        with tempfile.TemporaryDirectory() as root:
            c=Campo(Path(root));a=c.action('alice',{'action':'add','label':'A'})['account']
            data={'identity':'Alice','fingerprint':'alice','courses':[{'id':'c','name':'Lecture Math','active':True}],'study_planner':{'modules':[{'courses':[{'name':'Math','credits':2.5,'unit_id':'9'}]}]}}
            s=c.store('alice');s.save(a,data);s.close()
            state=c.snapshot('alice',a)
            self.assertNotIn('study_planner',state['data'])
            self.assertEqual(state['workspace']['courses_view'][0]['credits'],2.5)
            s=c.store('alice')
            try:self.assertEqual(s.read(a)['study_planner'],data['study_planner'])
            finally:s.close()
    def test_index_preserves_ambiguity_and_lecture_exercise_distinction(self):
        catalog={'modules':[{'courses':[{'name':'Math','credits':5,'unit_id':'1'},{'name':'Math Exercises','credits':2.5,'unit_id':'2'}]}]}
        index=credit_index(catalog)
        for name in ['Lecture Math','Tutorial/exercise Math Exercises','Missing']:
            self.assertEqual(credit_lookup(catalog,{'name':name}),credit_lookup(catalog,{'name':name},index=index))
