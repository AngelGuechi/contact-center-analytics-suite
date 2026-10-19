"""Serve only the two requested presentations and their named review files."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse

from qa_shared.paths import report_path

ROOT=Path(__file__).resolve().parent
ROUTES={}
ROUTES['/PORTABLE_SETUP.md']=(ROOT/'PORTABLE_SETUP.md','text/plain; charset=utf-8')
for prefix,folder in [('limited','01-limited-tools'),('ai','02-modern-ai')]:
    for url,name,mime in [('/','presentation.html','text/html; charset=utf-8'),('/spec.md','spec.md','text/plain; charset=utf-8'),('/output/QA_Review.xlsx','output/QA_Review.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')]:
        ROUTES['/'+prefix+url]=(report_path(folder) if name.startswith('output/') else ROOT/folder/name,mime)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        target=ROUTES.get(urlsplit(self.path).path)
        if not target or not target[0].is_file():self.send_error(404);return
        payload=target[0].read_bytes()
        self.send_response(200);self.send_header('Content-Type',target[1]);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    def log_message(self,*args):pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8803)
    args=parser.parse_args()
    print(f'Presentations: http://{args.host}:{args.port}/limited/ and http://{args.host}:{args.port}/ai/',flush=True)
    HTTPServer((args.host,args.port),Handler).serve_forever()
