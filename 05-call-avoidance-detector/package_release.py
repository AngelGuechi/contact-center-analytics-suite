"""Create a source ZIP without machine environments, runtime data or reviews."""
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parent
FILES = ["README.md", "HOW_TO_RUN.md", "BUILD_PLAN.md", "spec.md", "VALIDATION.md",
         "BENCHMARK_RESULTS.md", "INSTALL.bat", "RUN.bat", "CHECK.bat", "setup.py",
         "launch.py", "requirements.txt", "requirements.in", "config.example.json",
         "benchmark.py", "package_release.py", ".gitignore",
         "AUDIO_HOW_TO_RUN.md", "AUDIO_VALIDATION.md", "THIRD_PARTY_NOTICES.md", "update.md",
         "audio_setup.py", "audio_benchmark.py", "audio_model.source.json", "requirements-audio.txt",
         "INSTALL_AUDIO.bat", "CHECK_AUDIO.bat", "generate_recordings.py",
         "recordings/README.md", "recordings/manifest.json", "recordings/scripts.json", "recordings/recordings.csv",
         "data/manifest.json", "data/README.md", "data/expected_results.json"]
FOLDERS = ["avoidance", "tests", "fixtures", "data", "frontend/src", "frontend/dist"]
FRONTEND_FILES = ["frontend/package.json", "frontend/package-lock.json", "frontend/index.html", "frontend/vite.config.js"]


def build_release() -> Path:
    paths = [PROJECT / name for name in FILES + FRONTEND_FILES]
    for name in FOLDERS:
        paths.extend(path for path in (PROJECT / name).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix != ".pyc")
    # Package only the generated, allowlisted fixtures; never a user's audio.
    import json
    manifest = json.loads((PROJECT / 'recordings/manifest.json').read_text(encoding='utf-8'))
    import hashlib
    for entry in manifest['files']:
        path = PROJECT / 'recordings' / entry['file']
        if not path.resolve().is_relative_to(PROJECT / 'recordings/Calls') or path.is_symlink():
            raise RuntimeError('Invalid generated recording path.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                raise RuntimeError('Generated recording hash differs from its manifest.')
        paths.append(path)
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError("Complete release files first: " + ", ".join(missing))
    if not (PROJECT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Build the React interface before packaging.")
    destination = PROJECT / "runtime/releases/05-call-avoidance-detector-0.1.0-source.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            relative = path.relative_to(PROJECT)
            if path.is_symlink() or not path.resolve().is_relative_to(PROJECT):
                raise RuntimeError("Release files must stay inside the app folder.")
            bundle.write(path, str(Path(PROJECT.name) / relative))
    return destination


if __name__ == "__main__":
    print(build_release())
