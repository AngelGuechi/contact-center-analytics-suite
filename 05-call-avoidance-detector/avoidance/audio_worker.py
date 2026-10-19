"""Managed CPU worker; stdout contains JSON protocol only, one request at a time."""
from __future__ import annotations

import json
import os
import sys


def serve():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    for line in sys.stdin:
        try:
            request = json.loads(line)
            job_id = request["job_id"]
            def send(kind, **data):
                print(json.dumps({"type": kind, "job_id": job_id, **data}, allow_nan=False), flush=True)
            def progress(message, progress):
                send("progress", message=message, progress=progress)
            operation = request["operation"]
            if operation == "measure":
                from .audio_analysis import measure
                result = measure(request["path"], request.get("options"), progress)
            elif operation == "preview":
                from .audio_analysis import preview
                result = preview(request["path"], request.get("options"))
            elif operation == "transcribe":
                from .transcription import transcribe
                result = transcribe(request["path"], request.get("options"), progress)
            else:
                raise ValueError("Unsupported audio operation")
            expected = request.get('options', {}).get('expected_sha256')
            actual = result.get('source', {}).get('sha256') or result.get('source_sha256')
            if expected and expected != actual:
                raise ValueError('Retained recording bytes changed; restore the source or import a new revision before analysis.')
            send("result", result=result)
        except Exception as exc:
            print(json.dumps({"type": "error", "job_id": request.get("job_id") if isinstance(locals().get("request"), dict) else None,
                              "message": str(exc)}, allow_nan=False), flush=True)


if __name__ == "__main__":
    serve()
