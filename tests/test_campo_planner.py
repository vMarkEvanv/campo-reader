import unittest
from campo_backend.campo_planner import DOM,parse_modules,parse_tree,credit_lookup,post_view
from campo_backend.campo_workspace import course_credit_value
from campo_backend.campo_source.core import DataError

class PlannerTests(unittest.TestCase):
    def test_target_not_earned(self):
        dom=DOM('<h1 id="hisinoneTitle">Study planner with module plan Test</h1><table class="modulePlan"><tr><td><div class="headerModulePlan"><h3 id="x:popupTitleId">123 - Algebra</h3><span>0/7.5</span></div></td></tr></table>').root
        self.assertEqual(parse_modules(dom)[0]['credits'],7.5)
    def test_course_not_parent_credit(self):
        modules=[{'number':'123','credits':5,'courses':[]}]
        dom=DOM('<table class="treeTableWithIcons"><tr class="treeTableCellLevel1"><td><a class="linkTableTree" id="x:showModuleLink:link">123 | Module</a></td></tr><tr class="treeTableCellLevel2"><td><a class="linkTableTree" id="x:showPlanelementLink:link" href="?unitId=99">Lecture Algebra</a><span title="Credit Points">2.5</span></td></tr></table>').root
        parse_tree(dom,modules)
        value,unit,source=credit_lookup({'modules':modules},{'name':'Lecture Algebra'})
        self.assertEqual((value,unit,source),(2.5,'99','study_planner_course'))
        self.assertIsNone(credit_lookup({'modules':modules},{'name':'Exercises Algebra'})[0])
    def test_ambiguous_credits_not_guessed(self):
        rows=[{'courses':[{'name':'Algebra','credits':v,'unit_id':''}]} for v in (2.5,5)]
        self.assertIsNone(credit_lookup({'modules':rows},{'name':'Algebra'})[0])
    def test_manual_override_and_zero(self):
        row={'planner_credits':2.5}
        self.assertEqual(course_credit_value(row,{'credits':0},{'credit_value':5},{}),(0,'manual'))
        self.assertEqual(course_credit_value(row,{}, {'credit_value':5},{}),(2.5,'study_planner_course'))
    def test_registration_post_rejected(self):
        with self.assertRaises(DataError):post_view(None,'',None,'','register')

    def test_enrollment_type_prefix_and_exercise_distinction(self):
        catalog={'modules':[{'courses':[{'name':'Hardware-Software-Co-Design','credits':2.5,'unit_id':'1'},{'name':'Pattern Recognition Exercises','credits':1.25,'unit_id':'2'}]}]}
        self.assertEqual(credit_lookup(catalog,{'name':'Lecture Hardware-Software-Co-Design'})[0],2.5)
        self.assertEqual(credit_lookup(catalog,{'name':'Tutorial/exercise Pattern Recognition Exercises'})[0],1.25)
        self.assertIsNone(credit_lookup(catalog,{'name':'Lecture Pattern Recognition'})[0])

    def test_failed_refresh_preserves_catalog(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from campo_backend.campo import Campo
        with tempfile.TemporaryDirectory() as tmp:
            c=Campo(Path(tmp));u='alice';a=c.action(u,{'action':'add','label':'A'})['account']
            store=c.store(u)
            old={'identity':'Alice','fingerprint':'alice','study_planner':{'modules':[{'name':'keep'}]}}
            store.save(a,old);store.close()
            c.jobs[(u,a)]={'running':True};c.slots.acquire()
            with patch.object(c,'restore_session',return_value={}),patch('campo_backend.campo_planner.collect',side_effect=DataError('读取失败')):
                c.sync_planner(u,a)
            store=c.store(u)
            try:self.assertEqual(store.read(a)['study_planner'],old['study_planner'])
            finally:store.close()
