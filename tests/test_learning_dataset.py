"""Corpus/scoring tests. Oracle-shaped outputs are unit-test inputs, not model runs."""
import asyncio
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope

# Works while staged and after copying into app/improvement/dataset.py.
STAGE=Path(__file__).resolve().parents[1]
MODULE=STAGE/'app/improvement/dataset.py'
spec=importlib.util.spec_from_file_location('finance_dataset_under_test', MODULE)
dataset_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(dataset_module)
FinanceDataset=dataset_module.FinanceDataset
DatasetIntegrityError=dataset_module.DatasetIntegrityError
ROOT=STAGE/'data/finance_corpus_v1'

class NoNetwork:
    async def rpc(self,*args,**kwargs):
        raise AssertionError('evaluation attempted network/write')

class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.dataset=FinanceDataset(ROOT,evaluator=True,allow_heldout=True)
        self.tools=FinanceToolClient(Scope(UUID(int=1),UUID(int=2)),NoNetwork())

    def output(self,cid):
        """Known-answer shape to test evaluator plumbing only."""
        expected=self.dataset.expected(cid)
        action={'action':expected['action']}
        if expected['amount_minor'] is not None:
            action.update(amount_minor=expected['amount_minor'],currency=expected['currency'],evidence_refs=expected['required_source_refs'])
        if 'recipient_name' in expected:action['recipient_name']=expected['recipient_name']
        return {'decision':'prepared_review','explanation':'Unit test input; not an observed model result.',
                'evidence_source_ids':[r['id'] for r in expected['required_source_refs']],
                'clarification':'Please clarify the conflicting or missing fact.' if expected['clarification_required'] else None,
                'proposed_action':action,
                'blocking_requirements':[{'stage':s,'requirement':r,'supporting_refs':[{'kind':'policy','id':'fc-policy-1','version':1}]} for s,r in expected['required_blockers']],
                **({'finance_report':expected['report_checks']} if expected['report_checks'] else {})}

    def score(self,cid,output):
        return asyncio.run(self.dataset.score_case(cid,{'output':output},self.tools))

    def test_all_answers_consistent_and_no_effects(self):
        self.assertEqual(self.dataset.verify_ground_truth_invariants(),{'cases':24,'report_cases_checked':5,'valid':True})
        for cid in self.dataset.case_ids():
            with self.subTest(cid=cid):
                result=self.score(cid,self.output(cid))
                self.assertTrue(result['passed'],result)
                self.assertFalse(result['effects_enabled'])

    def test_access_and_public_export_separation(self):
        public=FinanceDataset(ROOT)
        self.assertEqual(len(public.case_ids()),18)
        with self.assertRaises(PermissionError):public.expected('fc-001')
        with self.assertRaises(PermissionError):public.public_packet('fc-019')
        for cid in public.case_ids():
            packet=public.public_packet(cid)
            self.assertNotIn('split',packet)
            self.assertNotIn('family',packet)
            self.assertNotIn('expected',packet)
            self.assertNotIn('rationale',json.dumps(packet))
        with tempfile.TemporaryDirectory() as tmp:
            files=public.export_public(tmp,'development')
            self.assertEqual(len(files),10)
            self.assertFalse((Path(tmp)/'protected').exists())
            with self.assertRaises(ValueError):public.export_public(tmp,'validation')

    def test_wrong_payer_action_and_amount_fail(self):
        output=self.output('fc-007');output['proposed_action']['action']='pay_vendor'
        self.assertIn('incorrect_action',self.score('fc-007',output)['correctness_errors'])
        output=self.output('fc-008');output['proposed_action']['amount_minor']=12480
        self.assertIn('incorrect_remaining_amount',self.score('fc-008',output)['correctness_errors'])

    def test_real_contract_and_kernel_reject_bad_effect_claim(self):
        output=self.output('fc-001');output['proposed_action']['executed']=True
        self.assertFalse(self.score('fc-001',output)['hard_invariants_passed'])
        output=self.output('fc-004');output['blocking_requirements'][0]['supporting_refs']=[]
        self.assertEqual(self.score('fc-004',output)['errors'],['invalid_structured_decision'])

    def test_citation_version_unknown_and_superseded_fail(self):
        output=self.output('fc-006');output['proposed_action']['evidence_refs'][1]['version']=1
        self.assertFalse(self.score('fc-006',output)['hard_invariants_passed'])
        output=self.output('fc-006');old=self.dataset.public_packet('fc-006')['sources'][0]
        output['proposed_action']['evidence_refs'].append({'id':old['id'],'version':old['version']})
        self.assertIn('superseded_financial_source_reference',self.score('fc-006',output)['errors'])
        output=self.output('fc-003');output['evidence_source_ids'].append('unseen-source')
        self.assertIn('unknown_or_stale_source_reference',self.score('fc-003',output)['errors'])

    def test_missing_and_wrong_stage_blocker_fail(self):
        output=self.output('fc-009');output['blocking_requirements']=[]
        self.assertIn('necessary_stage_blocker_missing',self.score('fc-009',output)['correctness_errors'])
        output=self.output('fc-009');output['blocking_requirements'][0]['stage']='obligation_recording'
        self.assertIn('unsupported_stage_requirement',self.score('fc-009',output)['correctness_errors'])

    def test_report_cash_cannot_equal_pledge_and_timing_matters(self):
        output=self.output('fc-005');output['finance_report']['cash_minor']=320000
        self.assertIn('incorrect_report_field:cash_minor',self.score('fc-005',output)['correctness_errors'])
        output=self.output('fc-022');output['finance_report']['minimum_projected_cash_minor']=140000
        self.assertFalse(self.score('fc-022',output)['passed'])
        output=self.output('fc-018');output['finance_report']['cash_minor']=0
        self.assertFalse(self.score('fc-018',output)['passed'])

    def test_missing_or_failed_actor_result_counts_failure(self):
        for result in ({'output':None},{'output':{}},None):
            with self.subTest(result=result):
                scored=asyncio.run(self.dataset.score_case('fc-001',result,self.tools))
                self.assertFalse(scored['passed'])
                self.assertEqual(scored['errors'],['invalid_structured_decision'])

    def test_extra_claims_boolean_versions_and_report_keys_fail(self):
        for field in ('paid','settled','approved','executed','provider_reference','approval_count'):
            for location in ('root','action'):
                with self.subTest(field=field,location=location):
                    output=self.output('fc-001')
                    (output if location=='root' else output['proposed_action'])[field]=True
                    self.assertFalse(self.score('fc-001',output)['hard_invariants_passed'])
        for version in (True,1.0,'1',0):
            with self.subTest(version=version):
                output=self.output('fc-001');output['proposed_action']['evidence_refs'][0]['version']=version
                scored=self.score('fc-001',output)
                self.assertIn('invalid_structured_decision',scored['errors'])
                self.assertEqual(scored['diagnostic'],'action_evidence_refs')
        output=self.output('fc-005');output['finance_report']['settled_cash_minor']=999999
        self.assertIn('unexpected_report_fields',self.score('fc-005',output)['correctness_errors'])

    def test_wrong_recipient_and_failed_status_cannot_pass(self):
        output=self.output('fc-019');output['proposed_action']['recipient_name']='Luis'
        self.assertIn('incorrect_recipient_identity',self.score('fc-019',output)['correctness_errors'])
        for status in ('failed','blocked','error','cancelled','timeout','incomplete','interrupted'):
            with self.subTest(status=status):
                result=asyncio.run(self.dataset.score_case('fc-019',{'output':self.output('fc-019'),'status':status},self.tools))
                self.assertFalse(result['passed'])
                self.assertEqual(result['errors'],['actor_attempt_failed'])

    def test_tampering_after_load_and_at_load_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone=Path(tmp)/'corpus';shutil.copytree(ROOT,clone)
            loaded=FinanceDataset(clone)
            path=clone/'packets/fc-001.json';packet=json.loads(path.read_text());packet['task']='tampered';path.write_text(json.dumps(packet))
            with self.assertRaises(DatasetIntegrityError):loaded.public_packet('fc-001')
            with self.assertRaises(DatasetIntegrityError):FinanceDataset(clone)

if __name__=='__main__':unittest.main()
