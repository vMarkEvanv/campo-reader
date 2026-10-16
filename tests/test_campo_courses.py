import copy
import unittest
from campo_backend import campo_courses as c, campo_workspace as w
from campo_backend.campo_source.core import DataError

class CourseTests(unittest.TestCase):
 def test_parser_only_courses_current_term_and_status(self):
  rows=[{'cells':['01','Lecture','Vorlesung','ZU','5','WS 2026/27']},{'cells':['02','Exam','Prüfung','AN','5','WS 2026/27']},{'cells':['03','Old','Seminar','ZU','5','SS 2026']},{'cells':['04','Wait','Seminar','WL','','WS 2026/27']}]
  result,info=c.parse_tables({'term':'Wintersemester 2026/27','tables':[{'headers':['Nummer','Veranstaltung','Art','Status','ECTS','Semester'],'rows':rows}]})
  self.assertEqual(len(result),3);self.assertTrue(result[0]['active']);self.assertFalse(result[2]['active']);self.assertEqual(result[0]['credit_value'],5)
  self.assertEqual(c.term_key('WS 2026/27'),c.term_key('Wintersemester 2026/27'))
 def test_exam_table_rejected(self):
  with self.assertRaises(DataError):c.parse_tables({'tables':[{'headers':['Name','Grade'],'rows':[]}]})
 def fixture(self):
  data={'grades':[{'kind':'module','name':'Passed','number':'1','status':'BE','credits':'5'},{'kind':'module','name':'Learning','number':'2','status':'AN','credits':'10'}]}
  modules=w.module_list(data)
  state={'groups':[{'id':'g','name':'Required','kind':'required','target':30}],'assignments':{modules[0]['id']:'g'},'planned':[]}
  course={'id':'a','name':'Learning','active':True,'ongoing':True,'confirmed':True,'will_exam':True,'group':'g','credits':10,'module_id':modules[1]['id']}
  return data,state,course,modules
 def test_two_segments_deduplicate_and_pass_transition(self):
  data,state,course,modules=self.fixture();second=dict(course,id='exercise');rows=[course,second]
  stat=w.progress_statistics(data,state,rows)[0];self.assertEqual((stat['earned'],stat['ongoing']),(5,10));self.assertEqual(course['count_reason'],'merged')
  data['grades'][1]['status']='BE';state['assignments'][modules[1]['id']]='g'
  stat=w.progress_statistics(data,state,rows)[0];self.assertEqual((stat['earned'],stat['ongoing']),(15,0));self.assertEqual(course['count_reason'],'already_passed')
 def test_interest_unknown_unconfirmed_not_counted(self):
  for patch,reason in [({'exercise':True},'exercise'),({'will_exam':False},'interest'),({'will_exam':None},'undecided'),({'confirmed':False},'unconfirmed'),({'module_id':'','credits':None},'unknown_credits')]:
   data,state,row,_=self.fixture();row.update(patch);self.assertEqual(w.progress_statistics(data,state,[row])[0]['ongoing'],0);self.assertEqual(row['count_reason'],reason)
 def test_manual_and_course_same_module_count_once(self):
  data,state,row,modules=self.fixture();state['planned']=[{'id':'p','name':'Manual','group':'g','credits':10,'module_id':modules[1]['id'],'status':'ongoing','will_exam':True}]
  self.assertEqual(w.progress_statistics(data,state,[row])[0]['ongoing'],10)
 def test_conflicting_group_is_excluded(self):
  data,state,row,_=self.fixture();state['groups'].append({'id':'b','name':'Other','target':20});second=dict(row,id='b',group='b')
  self.assertEqual(sum(x['ongoing'] for x in w.progress_statistics(data,state,[row,second])),0);self.assertEqual(row['count_reason'],'group_conflict')

 def test_real_campo_caption_table_and_exam_exclusion(self):
  table={'caption':'Course: Lecture Applied Mathematics','headers':['Dates and rooms','Status','Actions'],'rows':[{'cells':['Monday','Your actual status: Admitted','']}]}
  exam=dict(table,caption='Examination: Applied Mathematics')
  rows,_=c.parse_tables({'term':'Winter semester 2026/27','tables':[table,exam]})
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'Lecture Applied Mathematics');self.assertTrue(rows[0]['confirmed_enrollment']);self.assertIsNone(rows[0]['credit_value'])

 def test_classification_uses_intent_and_new_semester_stays_unclassified(self):
  raw={'id':'old','name':'Math','active':True,'source':'enrollments','confirmed_enrollment':True}
  fresh=dict(raw,id='new',semester='SS 2027')
  data={'courses':[raw,fresh]}
  for choice in ({'will_exam':True},{'will_exam':False},{'exercise':True}):
   rows=w.course_list(data,{'course_choices':{'old':choice}})
   self.assertTrue(rows[0]['classified']);self.assertFalse(rows[1]['classified'])
  rows=w.course_list(data,{'course_choices':{'old':{'will_exam':None,'exercise':False}}})
  self.assertFalse(rows[0]['classified'])

 def test_all_semesters_keep_same_course_separate(self):
  table={'headers':['Name','Semester','Status'],'rows':[{'cells':['Math','Summer semester 2026','ZU']},{'cells':['Math','Winter semester 2026/27','ZU']}]}
  rows,_=c.parse_tables({'term':'Winter semester 2026/27','tables':[table]})
  self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])

 def test_stale_semester_content_is_not_relabelled(self):
  table={'caption':'Course: Lecture Mathematics','headers':['Dates and rooms','Status','Actions'],'rows':[{'cells':['Monday','Your actual status: Admitted Term of the examination: SoSe 2026 Current attempt: 1','']}]}
  rows,_=c.parse_tables({'term':'Winter semester 2026/27','tables':[table]})
  self.assertEqual(c.term_key(rows[0]['semester']),'2026S')
  self.assertEqual(c.term_key('WiSe 2026'),'2026W')

 def test_completed_course_matches_unique_normalized_module_and_counts_once(self):
  grade={'kind':'module','name':'Introduction to machine learning','number':'65718','status':'BE','credits':'5.0'}
  data={'grades':[grade],'courses':[{'id':'lecture','name':'Lecture with exercise Introduction to Machine Learning','active':True,'confirmed_enrollment':True},{'id':'exercise','name':'Tutorial/exercise Introduction to Machine Learning Exercises','active':True,'confirmed_enrollment':True}]}
  module=w.module_list(data)[0]
  state={'groups':[{'id':'g','target':30}],'assignments':{module['id']:'g'},'planned':[],'course_choices':{'lecture':{'will_exam':True,'group':'g','credits':5}}}
  rows=w.course_list(data,state)
  self.assertTrue(all(r['completed'] for r in rows));self.assertTrue(all(r['module_id']==module['id'] for r in rows))
  stat=w.progress_statistics(data,state,rows)[0];self.assertEqual((stat['earned'],stat['ongoing']),(5,0));self.assertTrue(all(r['count_reason']=='already_passed' for r in rows))
  state['course_choices']['lecture']['module_id']='none'
  self.assertFalse(w.course_list(data,state)[0]['completed'])
 def test_similar_or_ambiguous_names_are_not_automatically_linked(self):
  data={'grades':[{'kind':'module','name':'Machine Learning','number':'1','program':'A','status':'BE','credits':'5'},{'kind':'module','name':'Machine Learning','number':'2','program':'B','status':'BE','credits':'5'}],'courses':[{'id':'a','name':'Lecture Machine Learning'},{'id':'b','name':'Lecture Introduction to Machine Learning'}]}
  rows=w.course_list(data,{})
  self.assertFalse(any(r['completed'] for r in rows));self.assertEqual(rows[0]['match_source'],'ambiguous');self.assertEqual(rows[1]['module_id'],'')

 def test_pass_transition_inherits_course_group_without_manual_assignment(self):
  data={'grades':[{'kind':'module','name':'Math','number':'M','status':'AN','credits':'5'}],'courses':[{'id':'c','name':'Lecture Math','active':True,'confirmed_enrollment':True}]}
  state={'groups':[{'id':'g','target':30}],'assignments':{},'planned':[],'course_choices':{'c':{'group':'g','will_exam':True,'credits':5}}}
  self.assertEqual(w.progress_statistics(data,state,w.course_list(data,state))[0]['ongoing'],5)
  data['grades'][0]['status']='BE'
  stat=w.progress_statistics(data,state,w.course_list(data,state))[0]
  self.assertEqual((stat['earned'],stat['ongoing']),(5,0))
 def test_repeated_unlinked_subject_is_one_module_across_semesters(self):
  data={'courses':[{'id':i,'name':'Lecture Math','number':'N','active':True,'confirmed_enrollment':True} for i in ('summer','winter')]}
  state={'groups':[{'id':'g','target':30}],'assignments':{},'planned':[],'course_choices':{i:{'group':'g','will_exam':True,'credits':5} for i in ('summer','winter')}}
  self.assertEqual(w.progress_statistics(data,state,w.course_list(data,state))[0]['ongoing'],5)
 def test_missing_reference_never_counts_as_independent_course(self):
  data={'courses':[{'id':'c','name':'Math','active':True,'confirmed_enrollment':True}]}
  state={'groups':[{'id':'g','target':30}],'assignments':{},'planned':[],'course_choices':{'c':{'group':'g','will_exam':True,'credits':5,'module_id':'planned:deleted'}}}
  rows=w.course_list(data,state);self.assertTrue(rows[0]['broken_link']);self.assertEqual(w.progress_statistics(data,state,rows)[0]['ongoing'],0);self.assertEqual(rows[0]['count_reason'],'broken_link')
 def test_auto_match_does_not_become_override_in_snapshot(self):
  data={'grades':[{'kind':'module','name':'Math','number':'M','status':'BE','credits':'5'}],'courses':[{'id':'c','name':'Lecture Math'}]}
  row=w.course_list(data,{})[0];self.assertTrue(row['module_id']);self.assertEqual(row['module_override'],'');self.assertEqual(row['match_source'],'name')

 def test_current_only_collect_does_not_visit_historical_terms(self):
  from unittest.mock import MagicMock,patch
  page=MagicMock();chosen=['Winter semester 2026/27']
  options=[{'value':'summer','label':'Summer semester 2026','disabled':False},{'value':'winter','label':'Winter semester 2026/27','disabled':False}]
  def evaluate(script):
   if script==c.NAV:return [{'id':'nav'}]
   if script==c.TERM_SELECTS:return [{'id':'terms','options':options}]
   if script==c.TABLES:return {'term':chosen[0],'empty':True,'tables':[]}
   raise AssertionError('Unexpected script')
  page.evaluate.side_effect=evaluate
  with patch.object(c,'identity'),patch.object(c,'activate'):
   rows,info=c.collect(page,'Alice','Winter semester 2026/27',current_only=True)
  self.assertEqual(rows,[]);self.assertEqual(info['scope'],'current');self.assertEqual(info['semesters'],['Winter semester 2026/27']);page.locator.return_value.select_option.assert_called_once_with('winter')
 def test_missing_semester_selector_never_replaces_all_history(self):
  from unittest.mock import MagicMock,patch
  page=MagicMock();page.evaluate.side_effect=[[{'id':'nav'}],[]]
  with patch.object(c,'identity'),patch.object(c,'activate'):
   with self.assertRaises(DataError):c.collect(page,'Alice','Winter semester 2026/27')

 def test_credited_exercise_counts_without_exam_and_deduplicates(self):
  data,state,row,modules=self.fixture();row.update(exercise=True,exercise_credits=True,will_exam=False)
  self.assertEqual(w.progress_statistics(data,state,[row])[0]['ongoing'],10)
  lecture=dict(row,id='lecture',exercise=False,will_exam=True)
  self.assertEqual(w.progress_statistics(data,state,[row,lecture])[0]['ongoing'],10)
  row['exercise_credits']=False
  self.assertEqual(w.progress_statistics(data,state,[row])[0]['ongoing'],0)
  self.assertEqual(row['count_reason'],'exercise')

 def test_credited_exercise_plan_counts_without_exam(self):
  data,state,row,modules=self.fixture()
  state['planned']=[{'id':'p','name':'Practical','group':'g','credits':3,'status':'ongoing','exercise':True,'exercise_credits':True,'will_exam':False,'module_id':''}]
  self.assertEqual(w.progress_statistics(data,state,[])[0]['ongoing'],3)
  state['planned'][0].pop('exercise_credits')
  self.assertEqual(w.progress_statistics(data,state,[])[0]['ongoing'],0)
