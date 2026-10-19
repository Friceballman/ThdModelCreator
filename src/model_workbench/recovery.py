"""Read-only handoff inspection. Never unlock, approve or retry work implicitly."""
from pathlib import Path

from .storage import WorkflowError, now, read, sha


def resume(workbench, project_id):
    store = workbench.store
    directory = store.directory(project_id)
    doc = store.load(project_id)
    files, issues = {}, []

    def inspect(value):
        if isinstance(value, dict):
            if 'file' in value and 'sha256' in value:
                key = (value['file'], value['sha256'])
                if key not in files:
                    try:
                        path = store.path(project_id, value['file'])
                        state = 'ok' if path.is_file() and sha(path) == value['sha256'] else 'missing_or_changed'
                    except (WorkflowError, OSError) as exc:
                        state = str(exc)
                    files[key] = {'file': value['file'], 'sha256': value['sha256'], 'state': state}
                    if state != 'ok':
                        issues.append(files[key])
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(doc)
    pending = [p for p in doc['plans'] if p['state'] in ('running', 'result_unknown', 'failed', 'blocked', 'awaiting_approval', 'approved', 'draft')]
    locks = []
    for path in (directory / '.mwb.lock', Path(__file__).resolve().parents[2] / 'experiments/runs/.execution.lock'):
        if path.exists():
            try:
                content = read(path)
            except (WorkflowError, OSError, ValueError):
                content = 'unreadable'
            locks.append({'path': str(path), 'content': content})
    checkpoints = []
    for path in (directory / 'recovery').glob('*.json'):
        try:
            saved = read(path)
            if saved.get('id') != project_id or saved.get('schema_version') != 1:
                raise WorkflowError('checkpoint ID/schema mismatch')
            checkpoints.append({'file': str(path), 'events': len(saved['events']), 'valid_json': True})
        except (WorkflowError, OSError, ValueError, KeyError, TypeError):
            checkpoints.append({'file': str(path), 'valid_json': False})
    return {'inspected_at': now(), 'project_directory': str(directory),
            'project': doc, 'status': workbench.status(project_id),
            'files': list(files.values()), 'file_issues': issues,
            'plans_needing_attention': pending, 'locks': locks,
            'checkpoints': checkpoints,
            'blender_files': [str(store.path(project_id, f['file'])) for c in doc['candidates']
                              for f in c['files'] if f['file'].endswith('.blend')],
            'instructions': 'Read project notes, requirements, plan prompts and approval evidence before continuing. '
                            'Inspect live processes and run logs for running/result_unknown. Do not delete locks, '
                            'retry, adopt assets or infer user approval automatically. Preserve the whole folder.'}
