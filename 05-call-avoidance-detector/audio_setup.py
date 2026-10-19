"""Optional, pinned CPU audio setup. Normal operation uses local assets only."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import venv

from setup import RuntimeLock, data_directory, environment_python

PROJECT = Path(__file__).resolve().parent
REPO = 'Systran/faster-whisper-base'
REVISION = 'ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66'
FILES = ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Check local installation without downloading.')
    parser.add_argument('--offline', action='store_true', help='Use preloaded model files and wheels only.')
    parser.add_argument('--wheel-dir', type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise RuntimeError('Audio setup uses 64-bit Python 3.12. Install it, then run INSTALL_AUDIO.bat again.')
    env = PROJECT / '.venv-audio'
    python = environment_python(env)
    model = PROJECT / 'runtime/models/whisper-base'
    pins = PROJECT / 'requirements-audio.txt'
    manifest = json.loads((PROJECT / 'audio_model.source.json').read_text(encoding='utf-8'))
    with RuntimeLock(data_directory(PROJECT) / 'runtime.lock'):
        if not args.check:
            if not python.is_file():
                venv.EnvBuilder(with_pip=True).create(env)
            command = [str(python), '-m', 'pip', 'install', '--only-binary=:all:', '-r', str(pins)]
            if args.offline:
                if not args.wheel_dir:
                    raise RuntimeError('Offline installation needs --wheel-dir and the preloaded model files.')
                command += ['--no-index', '--find-links', str(args.wheel_dir.resolve())]
            subprocess.run(command, check=True)
            if not args.offline and not all((model / name).is_file() for name in FILES):
                model.mkdir(parents=True, exist_ok=True)
                code = "from huggingface_hub import snapshot_download; snapshot_download(repo_id=" + repr(REPO) + ", revision=" + repr(REVISION) + ", local_dir=" + repr(str(model)) + ", allow_patterns=" + repr(list(FILES)) + ", token=False)"
                subprocess.run([str(python), '-c', code], check=True)
        if not python.is_file():
            raise RuntimeError('Run INSTALL_AUDIO.bat first.')
        subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
        for name, expected in manifest['files'].items():
            with (model / name).open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected['sha256']:
                raise RuntimeError('Model integrity check failed for ' + name + '. Restore the pinned model before running.')
        expected_pins = dict(line.strip().split('==', 1) for line in pins.read_text(encoding='utf-8').splitlines() if line.strip())
        probe = "from importlib.metadata import version; expected=" + repr(expected_pins) + "; assert all(version(name)==value for name,value in expected.items()), 'Package versions differ from the pinned audio profile'; import av,numpy,onnxruntime; from faster_whisper import WhisperModel; WhisperModel(" + repr(str(model)) + ",device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True); print('Local audio model verified.')"
        subprocess.run([str(python), '-c', probe], check=True, env={**os.environ, 'HF_HUB_OFFLINE': '1'})
        if not args.check:
            (env / 'audio_environment.json').write_text(json.dumps({'python': str(python), 'project': str(PROJECT),
                'requirements_sha256': hashlib.sha256(pins.read_bytes()).hexdigest(), 'model_revision': REVISION}), encoding='utf-8')
    print('Audio is ready. Start RUN.bat and open Recordings. No paid transcription service is used.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Audio setup: ' + str(exc), file=sys.stderr)
        sys.exit(1)
