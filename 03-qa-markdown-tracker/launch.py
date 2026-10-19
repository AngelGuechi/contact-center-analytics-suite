"""The same launch commands on Windows, macOS and Linux. No app runtime needed."""
import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def port(value):
    result = int(value)
    if not 1 <= result <= 65535:
        raise argparse.ArgumentTypeError('Use a port between 1 and 65535')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Launch a QA solution on this computer or server.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('limited', help='Create the Excel report; remaining options go to the report builder', add_help=False)
    for name, default in [('ai', 8503), ('presentations', 8803)]:
        command = sub.add_parser(name)
        command.add_argument('--host', default='127.0.0.1')
        command.add_argument('--port', type=port, default=default)
    sub.add_parser('test', help='Run the checks without an API key')
    sub.add_parser('doctor', help='Check Python, installed packages and the report timezone')
    args, remaining = parser.parse_known_args(argv)
    if remaining and args.command != 'limited':
        parser.error('Unrecognized options: ' + ' '.join(remaining))
    if sys.version_info < (3, 11):
        parser.error('Use Python 3.11 or newer; Python 3.12 is recommended.')
    if args.command == 'doctor':
        modules = ['openpyxl', 'streamlit', 'pandas', 'requests', 'matplotlib', 'altair', 'tzdata']
        missing = [name for name in modules if importlib.util.find_spec(name) is None]
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:ZoneInfo('America/Mexico_City')
        except ZoneInfoNotFoundError:missing.append('report timezone')
        print('Python:', sys.version.split()[0])
        print('Missing: ' + ', '.join(missing) if missing else 'Both solutions have their required packages and timezone.')
        if missing:print('Install with: python -m pip install -r requirements.txt')
        return int(bool(missing))
    if args.command == 'limited':
        command = [sys.executable, str(ROOT / '01-limited-tools/run.py'), *remaining]
        cwd = ROOT
    elif args.command == 'ai':
        command = [sys.executable, '-m', 'streamlit', 'run', str(ROOT / '02-modern-ai/app.py'),
                   '--server.address', args.host, '--server.port', str(args.port),
                   '--server.headless', 'true', '--browser.gatherUsageStats', 'false']
        cwd = ROOT / '02-modern-ai'
    elif args.command == 'presentations':
        command = [sys.executable, str(ROOT / 'preview_presentations.py'), '--host', args.host, '--port', str(args.port)]
        cwd = ROOT
    else:
        command = [sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'), '-v']
        cwd = ROOT
    try:
        return subprocess.call(command, cwd=cwd)
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
