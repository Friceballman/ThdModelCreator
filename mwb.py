"""Repository-local launcher. No install into the TripoSR environment required."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from model_workbench.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
