"""Execute case-specific Blender revisions with immutable inputs and run records."""
from pathlib import Path
import json
import os
import shutil
import sys
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'src'))
from model_workbench.storage import Store,read,write,sha,fingerprint,record,now
from model_workbench.runtime import load_config,process

PID='e2fbd0be-7077-4411-aab9-62fa8ce06c80'
store=Store(REPO/'projects');project=store.directory(PID)
case=project/'planning/rigging-v35-20261023'

def run_case(stage,script_path,parent_model,parameters,reason):
    context=case/f'iteration-{stage}-context.json'
    if context.exists():
        raise RuntimeError('This stage already has a run. Inspect it and use a new stage, never replay.')
    plan=record(kind='case_blender_revision',stage=stage,source=str(parent_model.relative_to(project)),
                source_hash=sha(parent_model),script_hash=sha(script_path),parameters=parameters,reason=reason,
                static_candidate_id='47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c',
                static_hash='f69f023673167b00b333bbfe132632f54ad4ad4d0fcf19e8f3dcee6bb7a3558f',
                approval='利用者の「要件を満たすまで反復してください。そして、完成したら確認用にいくつかアニメーションを作成」への明示指示。原本を保全し、衣服構造と頭部・眼球・内部身体の保持を満たすための派生修正。正式採用やUE確認は含まない。')
    plan['plan_hash']=fingerprint(plan)
    run=project/'runs'/plan['id'];run.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(parent_model,run/'input.blend');shutil.copyfile(script_path,run/'action.py')
    assert sha(run/'input.blend')==plan['source_hash'] and sha(run/'action.py')==plan['script_hash']
    pending=run/'outputs.pending';pending.mkdir()
    job=dict(source=str(run/'input.blend'),output=str(pending),parameters=parameters,
             adapter=str(REPO/'scripts/blender_rigging.py'),case=str(case),run_id=plan['id'])
    write(run/'job.json',job);plan['job_hash']=sha(run/'job.json')
    write(run/'plan.json',plan)
    state=dict(id=plan['id'],run=run.relative_to(project).as_posix(),stage=stage,state='approved',plan_hash=plan['plan_hash'])
    write(context,state)
    with store.update(PID,'rigging_case_revision_planned') as doc:
        doc.setdefault('notes',[]).append(record(kind='rigging_case_revision',text=reason,run=state['run'],plan_hash=plan['plan_hash']))
    lock=REPO/'experiments/runs/.execution.lock'
    with lock.open('x',encoding='utf-8') as stream:stream.write(plan['id'])
    try:
        state.update(state='running',started_at=now());write(context,state)
        metrics=process([load_config(REPO/'experiments/config.example.json')['blender'],'--background','--factory-startup','--disable-autoexec',
                         '--python-exit-code','1','--python',str(run/'action.py'),'--',str(run/'job.json')],run/'blender.log',dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),REPO)
        assert sha(parent_model)==plan['source_hash'] and sha(run/'input.blend')==plan['source_hash']
        assert sha(run/'action.py')==plan['script_hash'] and sha(run/'job.json')==plan['job_hash']
        assert read(pending/'checks.json')['success'] is True
        assert sha(project/'exports/fd13ce2d-48f8-4a61-b359-9a136387f79b/outputs/model.blend')==plan['static_hash']
        pending.rename(run/'outputs')
        state.update(state='succeeded',metrics=metrics,finished_at=now(),
                     files=[dict(file=p.relative_to(project).as_posix(),sha256=sha(p)) for p in sorted((run/'outputs').rglob('*')) if p.is_file()],
                     verification=dict(appearance='not_run',motion='not_run',ue='not_run'))
    except BaseException as exc:
        state.update(state='failed',error=str(exc),finished_at=now());write(context,state);raise
    finally:
        lock.unlink()
    write(context,state);print(json.dumps({k:v for k,v in state.items() if k!='files'}|dict(file_count=len(state.get('files',[]))),ensure_ascii=True));return state

if __name__=='__main__':
    parameters=read(sys.argv[4])
    run_case(sys.argv[1],Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve(),parameters,parameters['reason'])
