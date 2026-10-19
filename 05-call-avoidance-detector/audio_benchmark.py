"""Measure a local folder using the optional environment; never uploads audio."""
import argparse
import json
import platform
import time
from pathlib import Path

from avoidance.audio_analysis import measure
from avoidance.transcription import transcribe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--transcribe', action='store_true', help='Also benchmark transcription of these selected recordings.')
    parser.add_argument('--language', choices=['auto', 'en', 'es'], default='auto')
    parser.add_argument('--output', type=Path, default=Path('runtime/audio-benchmark.json'))
    args = parser.parse_args()
    files = sorted(path for path in args.folder.rglob('*') if path.is_file() and path.suffix.lower() in {'.wav', '.mp3'})
    rows, started = [], time.perf_counter()
    for index, path in enumerate(files):
        try:
            measurement = measure(path)
            row = {'file': str(path), 'duration_seconds': measurement['scope']['duration_seconds'],
                   'measurement_seconds': measurement['processing_seconds'], 'quiet_seconds': measurement['conversation']['totals']['quiet_seconds']}
            if args.transcribe:
                transcript = transcribe(path, {'language': args.language})
                row['transcription_seconds'] = transcript['processing_seconds']
                row['transcript'] = transcript['text']
            rows.append(row)
        except Exception as exc:
            rows.append({'file': str(path), 'error': str(exc)})
        print(f'{index + 1}/{len(files)} processed', flush=True)
    duration = sum(row.get('duration_seconds', 0) for row in rows)
    measurement_seconds = sum(row.get('measurement_seconds', 0) for row in rows)
    transcription_seconds = sum(row.get('transcription_seconds', 0) for row in rows)
    result = {'platform': platform.platform(), 'processor': platform.processor(), 'python': platform.python_version(),
              'recordings': len(files), 'failed': sum('error' in row for row in rows), 'audio_seconds': duration,
              'wall_seconds': time.perf_counter() - started,
              'measurement_rtf': measurement_seconds / duration if duration else None,
              'transcription_rtf': transcription_seconds / duration if duration and args.transcribe else None,
              'note': 'Only this input/host/profile was measured. Synthetic calls do not predict real-call accuracy or capacity.', 'results': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Results saved to {args.output.resolve()}')


if __name__ == '__main__':
    main()
