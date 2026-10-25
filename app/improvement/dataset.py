"""Frozen synthetic corpus I/O and evaluator. Never include this module's labels in actor context.

This adds an evaluation adapter, not an activation/promotion gate. No side effects,
mail, provider calls or live-model claims are made by these utilities.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.finance.types import FinanceError, cash_forecast, minor_units
from app.improvement.decisions import normalize_prepared_output
from app.resources import resource_path
from app.runtime.decision_contract import validate_decision_shape

DATASET_ID = 'finney-finance-corpus-v1'
MANIFEST_SHA256 = '8c01c438aa95cb12e5c53da562114f4c8ebd45bc83eae03d29ccf3cc13075e64'
DEFAULT_ROOT = resource_path('data/finance_corpus_v1')


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _refs(rows: list[dict]) -> set[tuple[str, int]]:
    return {(row['id'], row['version']) for row in rows}


class DatasetIntegrityError(ValueError):
    pass


class FinanceDataset:
    """Public material by default; answer access is an explicit evaluator capability.

    Capability flags prevent accidental mixing, not hostile same-user filesystem
    reads. The actual actor executor must receive only exported public packets.
    """

    def __init__(self, root: str | Path = DEFAULT_ROOT, *, evaluator: bool = False,
                 allow_heldout: bool = False):
        self.root = Path(root).resolve()
        self.evaluator, self.allow_heldout = evaluator, allow_heldout
        self.manifest = json.loads((self.root / 'manifest.json').read_text())
        content = dict(self.manifest)
        declared = content.pop('manifest_content_sha256', None)
        if declared != MANIFEST_SHA256 or declared != hashlib.sha256(_canonical(content)).hexdigest():
            raise DatasetIntegrityError('manifest content digest mismatch')
        if content.get('dataset_id') != DATASET_ID or content.get('case_count') != 24:
            raise DatasetIntegrityError('unsupported dataset identity/count')
        self._entries = {}
        for entry in self.manifest['entries']:
            path = self.root / entry['path']
            if not path.resolve().is_relative_to(self.root):
                raise DatasetIntegrityError('manifest path escapes dataset')
            if entry['path'] in self._entries:
                raise DatasetIntegrityError('duplicate manifest path')
            self._entries[entry['path']] = entry
            self._read(entry['path'])
        self._packets = {}
        for path in self._entries:
            if not path.startswith('packets/'):
                continue
            packet = self._read(path)
            cid = packet['case_id']
            if cid in self._packets or path != f'packets/{cid}.json':
                raise DatasetIntegrityError('duplicate or mismatched case id')
            if packet['split'] not in {'development', 'validation', 'heldout'}:
                raise DatasetIntegrityError('unknown split')
            refs = _refs(packet['sources'])
            if len(refs) != len(packet['sources']):
                raise DatasetIntegrityError('duplicate source/version')
            for source in packet['sources']:
                if hashlib.sha256(source['content'].encode()).hexdigest() != source['content_sha256']:
                    raise DatasetIntegrityError('source content digest mismatch')
            self._packets[cid] = packet
        counts = {s: sum(p['split'] == s for p in self._packets.values())
                  for s in ('development', 'validation', 'heldout')}
        if len(self._packets) != 24 or counts != self.manifest['split_counts']:
            raise DatasetIntegrityError('split/count mismatch')

    def _read(self, relative: str) -> dict:
        entry = self._entries.get(relative)
        if entry is None:
            raise DatasetIntegrityError('unmanifested file requested')
        raw = (self.root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise DatasetIntegrityError(f'file digest mismatch: {relative}')
        return json.loads(raw)

    def _case(self, case_id: str) -> dict:
        packet = self._packets[case_id]
        if packet['split'] == 'heldout' and not self.allow_heldout:
            raise PermissionError('heldout requires explicit final-evaluation capability')
        # Recheck bytes at every read, including after construction.
        return self._read(f'packets/{case_id}.json')

    def case_ids(self, split: str | None = None) -> list[str]:
        if split == 'heldout' and not self.allow_heldout:
            raise PermissionError('heldout access disabled')
        return sorted(cid for cid, p in self._packets.items()
                      if (split is None or p['split'] == split)
                      and (self.allow_heldout or p['split'] != 'heldout'))

    def public_packet(self, case_id: str) -> dict:
        packet = self._case(case_id)
        return copy.deepcopy({k: packet[k] for k in ('schema_version', 'case_id', 'title', 'sources', 'context', 'task')})

    def expected(self, case_id: str) -> dict:
        if not self.evaluator:
            raise PermissionError('answer access requires evaluator capability')
        self._case(case_id)
        return copy.deepcopy(self._read('protected/ground_truth.json')['cases'][case_id])

    def snapshot(self, case_id: str, scope: Any) -> dict:
        packet = self.public_packet(case_id)
        case_uuid = str(uuid5(NAMESPACE_URL, f'{scope.run_id}:{DATASET_ID}:{case_id}'))
        sources = [{**s, 'source_type': 'test_fixture', 'evidence_status': 'test_fixture',
                    'external_id': s['id']} for s in packet['sources']]
        ids = [s['id'] for s in sources]
        context = packet['context']
        return {'organization': {'id': str(scope.organization_id)},
                'run': {'id': str(scope.run_id), 'label': 'Explicit synthetic frozen corpus evaluation'},
                'immutable_policy': copy.deepcopy(context['policy']),
                'position': copy.deepcopy(context['position']),
                'budget': copy.deepcopy(context['budget']),
                'obligations': copy.deepcopy(context['obligations']),
                'source_items': sources,
                'cases': [{'id': case_uuid, 'version': 1, 'title': packet['title'], 'status': 'open',
                           'description': packet['task'], 'source_ids': ids,
                           'data': {'source_ids': ids, 'test_input': True},
                           'currency': context['position']['currency'], 'test_input': True}]}

    def export_public(self, destination: str | Path, split: str) -> list[Path]:
        """Export actor inputs only. Caller supplies this directory to executor."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        # Never merge into a directory containing hidden answers or other files.
        if any(destination.iterdir()):
            raise ValueError('public export destination must be empty')
        files = []
        for cid in self.case_ids(split):
            path = destination / f'{cid}.json'
            path.write_text(json.dumps(self.public_packet(cid), indent=2) + '\n')
            files.append(path)
        return files

    async def score_case(self, case_id: str, result: dict, tools: Any) -> dict:
        """Score every attempt; failures count. Uses the existing finance kernel.

        tools must be the trusted FinanceToolClient, never an actor-supplied tool
        object. Kernel validation runs on a captured prepare-only snapshot.
        """
        expected = self.expected(case_id)
        packet = self.public_packet(case_id)
        base = {'case_id': case_id, 'dataset_id': DATASET_ID,
                'manifest_sha256': self.manifest['manifest_content_sha256'],
                'effects_enabled': False, 'passed': False, 'hard_invariants_passed': False,
                'correctness_checks_passed': False, 'errors': [], 'correctness_errors': []}
        if isinstance(result, dict) and (result.get('status') in {'failed', 'blocked', 'error', 'cancelled', 'timeout', 'incomplete', 'interrupted'} or result.get('error')):
            return {**base, 'errors': ['actor_attempt_failed'], 'actor_status': result.get('status')}
        output = result.get('output', result) if isinstance(result, dict) else None
        try:
            if not isinstance(output, dict):
                raise TypeError('output object required')
            validate_decision_shape(output)
            normalized = normalize_prepared_output(output)
        except (ValueError, TypeError, AttributeError) as exc:
            return {**base, 'errors': ['invalid_structured_decision'], 'diagnostic': str(exc)}
        decision = normalized['proposed_action']
        sources = _refs(packet['sources'])
        source_ids = {s[0] for s in sources}
        policy = packet['context']['policy']
        policies = _refs([policy, *policy['rules']])
        hard, wrong = [], []
        forbidden_claims = {'executed', 'provider_reference', 'approved', 'approval_count', 'paid', 'settled'}
        if forbidden_claims & set(output) or forbidden_claims & set(decision):
            hard.append('decision_cannot_claim_external_effect_or_approval')
        # The runtime kernel validates versioned payment evidence and currency.
        try:
            scoped = tools.for_evaluation(self.snapshot(case_id, tools.scope))
            checked = await scoped.call('validate_prepared_decision', {'decision': decision})
            hard.extend(checked.get('errors', []))
            if not checked.get('hard_invariants_passed'):
                hard.append('finance_kernel_rejected')
        except (FinanceError, ValueError, TypeError, AttributeError, KeyError):
            hard.append('finance_kernel_validation_failed')
        refs = decision.get('evidence_refs', [])
        try:
            if not isinstance(refs, list) or any(not isinstance(ref, dict) or not isinstance(ref.get('id'), str) or not ref['id'] or type(ref.get('version')) is not int or ref['version'] < 1 for ref in refs):
                raise ValueError('invalid versioned evidence ref')
            cited = _refs(refs)
        except (KeyError, TypeError, ValueError):
            return {**base, 'errors': ['invalid_evidence_refs']}
        if not cited <= sources or not set(output['evidence_source_ids']) <= source_ids:
            hard.append('unknown_or_stale_source_reference')
        financial = decision.get('action') in {'pay_vendor', 'reimburse_organizer'}
        if financial:
            superseded = {s['id'] for s in packet['sources'] if s['metadata'].get('superseded')}
            if any(sid in superseded for sid, _ in cited):
                hard.append('superseded_financial_source_reference')
        required = _refs(expected['required_source_refs'])
        # Amount-bearing proposals cite operative sources by exact version.
        all_cited = cited | {(sid, version) for sid, version in sources if sid in output['evidence_source_ids']}
        if not required <= (cited if financial else all_cited):
            wrong.append('required_evidence_missing')
        if decision.get('action') != expected['action']:
            wrong.append('incorrect_action')
        if expected['amount_minor'] is not None:
            try:
                if minor_units(decision.get('amount_minor'), nonnegative=True) != expected['amount_minor']:
                    wrong.append('incorrect_remaining_amount')
            except FinanceError:
                wrong.append('invalid_remaining_amount')
            if decision.get('currency') != expected['currency']:
                wrong.append('incorrect_currency')
        if expected.get('recipient_name') is not None:
            recipient = decision.get('recipient_name')
            if not isinstance(recipient, str) or ' '.join(recipient.split()).casefold() != expected['recipient_name'].casefold():
                wrong.append('incorrect_recipient_identity')
        declared = set()
        for blocker in output['blocking_requirements']:
            pair = blocker['stage'], blocker['requirement']
            declared.add(pair)
            if list(pair) not in expected['allowed_blockers']:
                wrong.append('unsupported_stage_requirement')
            for ref in blocker['supporting_refs']:
                if (ref['id'], ref['version']) not in (policies if ref['kind'] == 'policy' else sources):
                    hard.append('unknown_blocker_support_reference')
        if not {tuple(p) for p in expected['required_blockers']} <= declared:
            wrong.append('necessary_stage_blocker_missing')
        if expected['clarification_required'] and not (isinstance(output['clarification'], str) and output['clarification'].strip()):
            wrong.append('necessary_clarification_missing')
        report_checks = expected['report_checks']
        report = output.get('finance_report')
        if report_checks and isinstance(report, dict) and set(report) != set(report_checks):
            wrong.append('unexpected_report_fields')
        for field, target in report_checks.items():
            if not isinstance(report, dict) or field not in report:
                wrong.append(f'missing_report_field:{field}')
                continue
            try:
                actual = None if report[field] is None else minor_units(report[field])
                if actual != target:
                    wrong.append(f'incorrect_report_field:{field}')
            except FinanceError:
                wrong.append(f'invalid_report_field:{field}')
        return {**base, 'passed': not hard and not wrong, 'hard_invariants_passed': not hard,
                'correctness_checks_passed': not wrong, 'errors': sorted(set(hard)),
                'correctness_errors': sorted(set(wrong)), 'normalized_output': normalized}

    def verify_ground_truth_invariants(self) -> dict:
        """Author/evaluator arithmetic checks using the real cash-forecast kernel.

        This verifies internal consistency, never independent finance validation.
        """
        if not self.evaluator:
            raise PermissionError('evaluator capability required')
        checked = 0
        for cid in self.case_ids():
            packet, expected = self.public_packet(cid), self.expected(cid)
            report = expected['report_checks']
            context = packet['context']
            if not _refs(expected['required_source_refs']) <= _refs(packet['sources']):
                raise DatasetIntegrityError(f'unknown expected reference: {cid}')
            if not report:
                continue
            forecast = cash_forecast(context['position']['cash_minor'], context['obligations'], currency='USD')
            if 'projected_cash_minor' in report:
                projection = forecast['projected_cash_minor']
                projection = None if projection is None else int(projection)
                if projection != report['projected_cash_minor']:
                    raise DatasetIntegrityError(f'forecast label mismatch: {cid}')
            payables = sum(int(o['amount_minor']) - int(o.get('settled_minor', 0)) for o in context['obligations'] if o['direction'] == 'payable' and o['status'] not in {'settled', 'cancelled'})
            receivables = sum(int(o['amount_minor']) - int(o.get('settled_minor', 0)) for o in context['obligations'] if o['direction'] == 'receivable' and o['status'] not in {'settled', 'cancelled'})
            for field, value in [('remaining_payables_minor', payables), ('expected_receivables_minor', receivables)]:
                if field in report and report[field] != value:
                    raise DatasetIntegrityError(f'obligation label mismatch: {cid}:{field}')
            if 'minimum_projected_cash_minor' in report:
                minimum = min([int(forecast['opening_minor']), *[int(r['projected_cash_minor']) for r in forecast['rows']]])
                if minimum != report['minimum_projected_cash_minor']:
                    raise DatasetIntegrityError(f'timing label mismatch: {cid}')
            checked += 1
        return {'cases': len(self.case_ids()), 'report_cases_checked': checked, 'valid': True}
