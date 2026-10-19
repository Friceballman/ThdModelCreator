"""Execute upstream run.py without editing its environment or source."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    for name in ('root', 'image', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--chunk-size', required=True, type=int)
    parser.add_argument('--mc-resolution', required=True, type=int)
    args = parser.parse_args()
    import torch
    import numpy as np
    import torchmcubes
    from PIL import Image
    image_path = Path(args.image).resolve()
    with Image.open(image_path) as image:
        image.verify()
    if not (Path(os.environ['U2NET_HOME']) / 'u2net.onnx').is_file():
        raise RuntimeError('既存のu2net.onnxがありません。自動取得せず停止します')
    if not torch.cuda.is_available() or not torchmcubes.HAS_CUDA:
        raise RuntimeError('CUDA／torchmcubes CUDAが利用不可。CPUへ自動切替しません')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    metrics = {'torch': torch.__version__, 'numpy': np.__version__,
               'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0)}
    sys.path.insert(0, str(Path(args.root).resolve()))
    sys.argv = [str(Path(args.root) / 'run.py'), str(image_path), '--device', 'cuda:0',
                '--chunk-size', str(args.chunk_size), '--mc-resolution', str(args.mc_resolution),
                '--model-save-format', 'obj', '--output-dir', str(output)]
    try:
        runpy.run_path(sys.argv[0], run_name='__main__')
        import trimesh
        mesh = trimesh.load(output / '0/mesh.obj', force='mesh', process=False)
        if not (len(mesh.vertices) and len(mesh.faces) and np.isfinite(mesh.vertices).all()
                and mesh.faces.min() >= 0 and mesh.faces.max() < len(mesh.vertices)):
            raise RuntimeError('生成メッシュの検証が不合格')
        metrics.update(success=True, vertices=len(mesh.vertices), faces=len(mesh.faces),
                       watertight=bool(mesh.is_watertight))
    except BaseException as exc:
        metrics.update(success=False, error=repr(exc))
        raise
    finally:
        metrics.update(seconds=time.perf_counter() - started,
                       cuda_peak_allocated_mib=torch.cuda.max_memory_allocated() / 2**20,
                       cuda_peak_reserved_mib=torch.cuda.max_memory_reserved() / 2**20)
        (output / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
        print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
