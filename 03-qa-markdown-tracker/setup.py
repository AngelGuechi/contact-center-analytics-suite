"""Create a project-local Python environment on Windows, macOS or Linux."""
import argparse
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limited', action='store_true', help='Install only the Excel solution')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Install Python 3.11 or newer. Python 3.12 is recommended.')
    target = ROOT / '.venv'
    print('Preparing the QA environment...', flush=True)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    ready = False
    if python.is_file():
        try:
            check = subprocess.run([str(python), '-c', 'import sys, pip; assert sys.version_info >= (3, 11)'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ready = check.returncode == 0
        except OSError:
            pass
    if not ready:
        venv.EnvBuilder(with_pip=True).create(target)
    requirements = ROOT / ('01-limited-tools/requirements.txt' if args.limited else 'requirements.txt')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
    relative = '.venv\\Scripts\\python.exe' if sys.platform == 'win32' else '.venv/bin/python'
    print(f'Ready. Create the report: {relative} launch.py limited --demo')
    if not args.limited:print(f'Open the dashboard: {relative} launch.py ai')


if __name__ == '__main__':
    main()
