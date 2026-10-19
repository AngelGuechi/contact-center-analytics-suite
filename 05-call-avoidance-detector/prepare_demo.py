"""Generate the fictional workbook inputs used by the portable test suite."""
from pathlib import Path
from avoidance.fixtures import generate_demo

if __name__ == '__main__':
    root=Path(__file__).resolve().parent
    for folder in ('fixtures','data'):
        generate_demo(root/folder)
    print('Prepared synthetic fixture and import folders; no operational inputs were read.')
