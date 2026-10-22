"""Call connect/capture through Blender MCP; returns and saves observed state."""
import hashlib
import json
from pathlib import Path

import bpy


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def load_session(manifest_path):
    manifest = Path(manifest_path).resolve()
    return manifest, json.loads(manifest.read_text(encoding='utf-8'))

def transforms():
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            part_id = obj.get('part_id') or obj.get('mwb_part_id')
            result.setdefault(part_id, {})[obj.name] = dict(
                location=list(obj.location), rotation=list(obj.rotation_euler), scale=list(obj.scale))
    return result


def connect(manifest_path, open_copy=False):
    manifest, session = load_session(manifest_path)
    working = Path(session['working_path']).resolve()
    if bpy.data.is_dirty:
        raise ValueError('接続前のシーンに未保存変更があります。保存状態を確認してください')
    if Path(bpy.data.filepath).resolve() != working:
        if not open_copy:
            raise ValueError('接続先のファイルが違います。作業コピーを開いてください')
        if bpy.data.is_dirty:
            raise ValueError('現在のBlenderに未保存変更があります。保存後に再接続してください')
        bpy.ops.wm.open_mainfile(filepath=str(working), use_scripts=False)
    if digest(working) != session['source_sha256']:
        raise ValueError('初回接続前に作業コピーが変更されています')
    bpy.context.scene['mwb_session_id'] = session['id']
    bpy.context.scene['mwb_source_candidate_id'] = session['candidate_id']
    result = dict(session_id=session['id'], candidate_id=session['candidate_id'],
                  filepath=str(working), sha256=digest(working),
                  blender_version=bpy.app.version_string,
                  transforms=transforms(),
                  objects=[{'name': o.name, 'part_id': o.get('part_id') or o.get('mwb_part_id')}
                           for o in bpy.context.scene.objects if o.type == 'MESH'])
    (manifest.parent / 'connection.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def capture(manifest_path, operations):
    manifest, session = load_session(manifest_path)
    working = Path(session['working_path']).resolve()
    if (Path(bpy.data.filepath).resolve() != working or
            bpy.context.scene.get('mwb_session_id') != session['id'] or
            bpy.context.scene.get('mwb_source_candidate_id') != session['candidate_id']):
        raise ValueError('編集シーンが接続済みセッションと一致しません')
    if not isinstance(operations, list) or not operations:
        raise ValueError('実行した操作をoperationsとして記録してください')
    bpy.ops.wm.save_as_mainfile(filepath=str(working))
    result = dict(session_id=session['id'], candidate_id=session['candidate_id'],
                  filepath=str(working), sha256=digest(working), operations=operations,
                  transforms=transforms())
    (manifest.parent / 'capture.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
