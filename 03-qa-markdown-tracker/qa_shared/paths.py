"""Portable source and storage locations; private files are optional for a demo."""
import os
from pathlib import Path

from .core import DataError
from .demo import ensure_demo, ensure_sample

ROOT = Path(__file__).resolve().parents[1]


def data_root():
    return Path(os.environ.get('QA_DATA_DIR') or ROOT).expanduser().resolve()


def source_paths(input_folder=None, sample_file=None, *, demo=False):
    configured = None if demo else (input_folder or os.environ.get('QA_INPUT_FOLDER'))
    if configured:
        folder = Path(configured).expanduser().resolve()
        if not folder.is_dir():
            raise DataError('The configured input folder does not exist')
    else:
        folder = ensure_demo(data_root() / 'demo-data')
    explicit_sample = sample_file or os.environ.get('QA_SAMPLE_FILE')
    if explicit_sample:
        sample = Path(explicit_sample).expanduser().resolve()
        if not sample.is_file():
            raise DataError('The configured call sample does not exist')
    else:
        sample = next(iter(sorted(ROOT.glob('*.ods'))), None)
        if sample is None and (folder / 'SYNTHETIC-DEMO.json').exists():
            sample = ensure_sample(data_root() / 'runtime' / 'Synthetic_sample.ods')
    return folder, sample


def store_path():
    return Path(os.environ.get('QA_STORE_PATH') or data_root() / '02-modern-ai/runtime/qa.db').expanduser().resolve()


def report_path(solution):
    return data_root() / solution / 'output' / 'QA_Review.xlsx'
