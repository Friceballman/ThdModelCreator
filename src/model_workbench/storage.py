from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid


class WorkflowError(ValueError):
    pass


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise WorkflowError('IDは完全なUUID v4を指定してください') from exc
    if parsed.version != 4:
        raise WorkflowError('UUID v4以外は使用できません')
    return str(parsed)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def no_links(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        if node.is_symlink() or (node.exists() and
                getattr(node.lstat(), 'st_file_attributes', 0) & 0x400):
            raise WorkflowError(f'リンク・ジャンクションは使用できません: {node}')
    return path.resolve()


def read(path):
    with no_links(path).open(encoding='utf-8-sig') as stream:
        return json.load(stream, parse_constant=lambda x: (_ for _ in ()).throw(
            WorkflowError(f'非有限JSON値は使用できません: {x}')))


def write(path, value):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uid() + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def record(**fields):
    return dict(id=uid(), created_at=now(), **fields)


def find(items, item_id):
    item_id = identifier(item_id)
    matches = [item for item in items if item.get('id') == item_id]
    if len(matches) != 1:
        raise WorkflowError(f'対象が見つからないかIDが重複しています: {item_id}')
    return matches[0]


class Store:
    def __init__(self, root):
        self.root = no_links(root)

    def directory(self, project_id):
        return self.root / identifier(project_id)

    def path(self, project_id, relative):
        value = Path(relative)
        if value.is_absolute() or '..' in value.parts or '\\' in str(relative):
            raise WorkflowError('管理パスは案件内の相対POSIXパスが必要です')
        path = no_links(self.directory(project_id) / value)
        if not path.is_relative_to(self.directory(project_id)):
            raise WorkflowError('案件外のパスです')
        return path

    def load(self, project_id):
        doc = read(self.directory(project_id) / 'project.json')
        if doc.get('schema_version') != 1 or doc.get('id') != identifier(project_id):
            raise WorkflowError('未知schemaまたは案件ID不一致。上書きせず停止します')
        for collection in ('references', 'requirements', 'part_plans', 'plans',
                           'candidates', 'materials', 'reviews', 'exports', 'events'):
            if not isinstance(doc.get(collection), list):
                raise WorkflowError(f'案件データが破損しています: {collection}')
        if doc.get('workflow_version', 1) not in (1, 2, 3):
            raise WorkflowError('未知の制作ワークフロー版です')
        for collection in ('production_plans', 'reference_packs', 'quality_issues',
                           'edit_sessions', 'completion_history', 'comparisons'):
            if not isinstance(doc.get(collection, []), list):
                raise WorkflowError(f'案件データが破損しています: {collection}')
        return doc

    def save(self, doc):
        # An immutable full checkpoint precedes replacing the primary index.
        # It also preserves enough context when the primary JSON is damaged.
        directory = self.directory(doc['id'])
        write(directory / 'recovery' / (uid() + '.json'), doc)
        write(directory / 'project.json', doc)

    def create(self, name, goal, workflow_version=2):
        if not name.strip() or not goal.strip():
            raise WorkflowError('案件名と目的は空にできません')
        self.root.mkdir(parents=True, exist_ok=True)
        if workflow_version not in (2, 3):
            raise WorkflowError('新規案件のworkflow_versionは2または3です')
        doc = record(schema_version=1, workflow_version=workflow_version, name=name, goal=goal, state='active',
                     approved_candidate_id=None, references=[], requirements=[],
                     part_plans=[], plans=[], candidates=[], materials=[],
                     reviews=[], exports=[], events=[], notes=[],
                     production_plans=[], reference_packs=[])
        directory = self.directory(doc['id'])
        directory.mkdir(exist_ok=False)
        self.save(doc)
        return doc

    def list(self):
        if not self.root.exists():
            return []
        return [self.load(p.parent.name) for p in sorted(self.root.glob('*/project.json'))]

    @contextmanager
    def update(self, project_id, event):
        directory = self.directory(project_id)
        no_links(directory)
        lock = directory / '.mwb.lock'
        try:
            with lock.open('x', encoding='utf-8') as stream:
                json.dump({'pid': os.getpid(), 'created_at': now()}, stream)
        except FileExistsError as exc:
            raise WorkflowError('案件ロックが存在します。実行状態を確認し、自動で削除しないでください') from exc
        try:
            doc = self.load(project_id)
            if doc['state'] != 'active':
                raise WorkflowError('アーカイブ済み案件は読み取り専用です')
            yield doc
            doc['events'].append(record(event=event))
            self.save(doc)
        finally:
            lock.unlink()
