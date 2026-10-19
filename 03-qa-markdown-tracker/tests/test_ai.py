import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'02-modern-ai'))
sys.path.insert(0,str(ROOT))
from storage import Store
from ai_service import generate,packet_for,usage_cost,masked,validate
from qa_shared.core import build_report
from test_core import audit,dataset


class Response:
    def __init__(self,result=None,status=200):self.result=result;self.status_code=status
    def json(self):return self.result

def valid_draft():
    return {'summary':'Review the existing OIR finding.','goal':'Improve ownership on the next reviewed calls.',
            'reality':'The recorded finding is the starting point.','options':'Listen to the cited call and agree a practical change.',
            'will':'Agree a follow-up date.','evidence_ids':['E1'],'themes':[]}

def result(draft=None,status='completed'):
    return {'status':status,'usage':{'input_tokens':2000,'input_tokens_details':{'cached_tokens':0},'output_tokens':800},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(draft or valid_draft())}]}]}


class AITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'qa.db')
        self.report=build_report(dataset([audit(1,'2026-08-30',60,md='OIR')]),'2026-08-31')
        self.calls=[]
    def tearDown(self):self.temp.cleanup()
    def post(self,*args,**kwargs):
        self.calls.append(kwargs)
        return Response(result())
    def run_ai(self,**options):return generate(self.store,self.report,'test-key',post=self.post,**options)

    def test_twenty_synthetic_requests_validate_and_bill(self):
        for i in range(20):
            draft,refs,_=self.run_ai(question='Discuss the recorded finding '+str(i))
            self.assertEqual(draft['evidence_ids'],['E1'])
            self.assertEqual(refs['E1']['audit_id'],'1')
        self.assertEqual(len(self.calls),20)
        self.assertAlmostEqual(self.store.spend(),20*.00042)

    def test_cache_saves_repeated_api_calls(self):
        self.run_ai();_,_,label=self.run_ai()
        self.assertEqual(len(self.calls),1);self.assertIn('no new API charge',label)

    def test_changed_data_invalidates_cache(self):
        self.run_ai()
        self.report=build_report(dataset([audit(1,'2026-08-30',70,md='OIR')]),'2026-08-31')
        self.run_ai();self.assertEqual(len(self.calls),2)

    def test_request_is_structured_minimal_and_not_stored(self):
        self.run_ai();payload=self.calls[0]['json']
        self.assertFalse(payload['store']);self.assertEqual(payload['reasoning']['effort'],'minimal')
        self.assertTrue(payload['text']['format']['strict']);self.assertEqual(payload['max_output_tokens'],2000)

    def test_luna_uses_no_reasoning_and_explicit_cost(self):
        self.run_ai(model='gpt-6-luna')
        self.assertEqual(self.calls[0]['json']['reasoning']['effort'],'none')
        self.assertAlmostEqual(self.store.spend(),.00065)

    def test_budget_blocks_before_transport(self):
        with self.assertRaisesRegex(ValueError,'budget'):self.run_ai(budget=0)
        self.assertEqual(self.calls,[])

    def test_no_key_no_request(self):
        with self.assertRaisesRegex(ValueError,'API key'):generate(self.store,self.report,'',post=self.post)
        self.assertEqual(self.calls,[])

    def test_timeout_keeps_reservation(self):
        def failed(*a,**k):raise requests.Timeout()
        with self.assertRaisesRegex(ValueError,'connection failed'):generate(self.store,self.report,'test-key',post=failed)
        self.assertGreater(self.store.spend(),0);self.assertIn('Unknown',self.store.ledger()[0]['State'])

    def test_http_failure_does_not_publish_or_log_key(self):
        for status in [401,429,500]:
            with self.assertRaisesRegex(ValueError,str(status)):
                generate(self.store,self.report,'private-test-key',post=lambda *a,**k:Response(status=status))
        self.assertEqual(self.store.spend(),0)
        self.assertNotIn('private-test-key',json.dumps(self.store.ledger()))

    def test_bad_citation_rejected_after_usage_recorded(self):
        draft=valid_draft();draft['evidence_ids']=['NOT-AN-AUDIT']
        with self.assertRaisesRegex(ValueError,'unavailable evidence'):
            generate(self.store,self.report,'test-key',post=lambda *a,**k:Response(result(draft)))
        self.assertAlmostEqual(self.store.spend(),.00042)

    def test_numeric_prose_rejected(self):
        draft=valid_draft();draft['summary']='QA is 99%.'
        with self.assertRaisesRegex(ValueError,'numeric'):validate(draft,{'E1':{'comment':''}})

    def test_incomplete_and_refusal_rejected(self):
        with self.assertRaisesRegex(ValueError,'did not finish'):
            generate(self.store,self.report,'key',post=lambda *a,**k:Response(result(status='incomplete')))
        refused=result();refused['output'][0]['content']=[{'type':'refusal','refusal':'No'}]
        with self.assertRaisesRegex(ValueError,'declined'):
            generate(self.store,self.report,'key',post=lambda *a,**k:Response(refused))

    def test_names_contacts_and_ids_are_masked(self):
        a=audit(1,'2026-08-30',md='OIR');a['agent']='María López'
        a['comment']='María López email: maria@example.com; phone: 555-123-4567; audit 1'
        report=build_report(dataset([a]),'2026-08-31')
        packet,_=packet_for(report)
        wire=json.dumps(packet,ensure_ascii=False)
        self.assertNotIn('María López',wire);self.assertNotIn('maria@example.com',wire);self.assertNotIn('555-123',wire)
        self.assertNotIn('audit_ids',wire)
        self.assertEqual(report['detail'][0]['agent'],'María López')

    def test_cached_token_price(self):
        self.assertAlmostEqual(usage_cost('gpt-5-nano',{'input_tokens':2000,'input_tokens_details':{'cached_tokens':1000},'output_tokens':800}),.000375)

    def test_coaching_survives_reimport_and_validates_follow_up(self):
        data=dataset([]);self.store.publish(data)
        entry={'agent_id':'a','date':'2026-08-20','follow_up':'2026-08-31','action':'Review OIR','markdown':'OIR','owner':'Supervisor'}
        self.store.save_coaching(entry);self.store.publish(data)
        self.assertEqual(self.store.coaching(),[entry])
        entry['follow_up']='2026-08-01'
        with self.assertRaises(ValueError):self.store.save_coaching(entry)


if __name__=='__main__':unittest.main()
