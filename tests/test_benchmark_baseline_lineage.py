"""Reference-lineage fixtures only. No provider calls, activation or DB writes."""
import copy
import hashlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

STAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("staged_benchmark_lineage",STAGE/'app/improvement/benchmark.py')
benchmark=importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
BASELINE="# Exact bundled baseline\n\nRetain every byte, including this newline.\n"
BASELINE_HASH=hashlib.sha256(BASELINE.encode()).hexdigest()


class Port:
    def __init__(self,active=None,*,bad_artifact=False):
        self.active=copy.deepcopy(active)
        self.calls=[]
        self.versions={active['id']:copy.deepcopy(active)} if active else {}
        self.artifacts={}
        self.evaluations={}
        self.bad_artifact=bad_artifact

    async def call(self,name,args):
        self.calls.append((name,copy.deepcopy(args)))
        if name=='get_active_skill':return copy.deepcopy(self.active)
        if name=='put_artifact':
            sha=hashlib.sha256(args['content'].encode()).hexdigest()
            path='private-fixture/'+sha+'/'+args['name'];self.artifacts[path]=args['content']
            return {'artifact_path':path,'content_sha256':'0'*64 if self.bad_artifact else sha}
        if name=='save_skill_version':
            row={'id':str(uuid4()),'is_active':False,**copy.deepcopy(args)}
            self.versions[row['id']]=row
            return copy.deepcopy(row)
        if name=='record_eval_run':
            self.evaluations[args['id']]=copy.deepcopy(args)
            return copy.deepcopy(args)
        raise AssertionError('unexpected operation: '+name)


def experiment(tmp_path,port):
    exp=object.__new__(benchmark.HostedExperiment)
    exp.id=str(uuid4());exp.tools=port;exp.root=tmp_path;exp.baseline=BASELINE
    exp.baseline_version=exp.candidate_version=None;exp.receipts=[];exp.evaluation_recorded=False
    return exp


@pytest.mark.asyncio
@pytest.mark.parametrize('active_kind',['absent','mismatching'])
async def test_missing_or_different_active_gets_exact_nonactive_reference_and_links(tmp_path,active_kind):
    active=({'id':str(uuid4()),'content_sha256':'1'*64,'is_active':True,'artifact_path':'old-active'}
            if active_kind=='mismatching' else None)
    port=Port(active);before=copy.deepcopy(port.active);exp=experiment(tmp_path,port)
    receipt=await exp.ensure_baseline_reference()
    reference=port.versions[exp.baseline_version]
    assert reference['content_sha256']==BASELINE_HASH
    assert port.artifacts[reference['artifact_path']]==BASELINE
    assert reference['status']=='baseline_reference'
    assert reference['parent_version_id'] is None and reference['is_active'] is False
    assert receipt['reused_matching_active'] is False
    assert port.active==before
    candidate=await port.call('save_skill_version',{'skill_name':'organizer-expenses','status':'candidate',
        'content_sha256':'2'*64,'parent_version_id':exp.baseline_version})
    exp.candidate_version=candidate['id']
    await exp.evaluation_state('candidate_created',{'fixture':True})
    assert port.versions[exp.candidate_version]['parent_version_id']==reference['id']
    assert port.evaluations[exp.id]['baseline_version_id']==reference['id']
    assert port.evaluations[exp.id]['candidate_version_id']==candidate['id']
    assert not any(name in {'initialize_skill_baseline','set_active_skill_version','rollback_skill_version'} for name,_ in port.calls)


@pytest.mark.asyncio
async def test_matching_active_reference_is_reused_without_saving_skill(tmp_path):
    active={'id':str(uuid4()),'content_sha256':BASELINE_HASH,'is_active':True,'artifact_path':'existing-baseline'}
    port=Port(active);exp=experiment(tmp_path,port)
    receipt=await exp.ensure_baseline_reference()
    assert exp.baseline_version==active['id']
    assert receipt['reused_matching_active'] is True
    assert len(port.versions)==1 and port.active==active
    assert not any(name=='save_skill_version' for name,_ in port.calls)


@pytest.mark.asyncio
async def test_reference_fails_closed_on_wrong_artifact_digest(tmp_path):
    from app.models import ModelError
    port=Port(bad_artifact=True);exp=experiment(tmp_path,port)
    with pytest.raises(ModelError,match='baseline_artifact_hash_mismatch'):
        await exp.ensure_baseline_reference()
    assert exp.baseline_version is None and not port.versions
