import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from qa_shared.core import load_sources,build_report
from qa_shared.paths import source_paths, report_path
from qa_shared.excel_report import write_report
data=load_sources(*source_paths(demo=True))
report=build_report(data)
write_report(report,report_path('02-modern-ai'))
print(report['summary'])
