#!/usr/bin/env bash
# Direct-download beta; PySide/Torch wheels, source-patched Qt and Qwen.
# Requires the user-installed Flatpak runtimes pinned by flatpak-release.yml.
# Builds a committed checkout in its own directory; never installs the app.
set -euo pipefail

if [[ ${1:-} == --help ]]; then
    echo 'Usage: scripts/build-release-flatpak.sh [output-directory]'
    echo 'Build the committed beta using org.flatpak.Builder and KDE SDK/Platform 6.11.'
    echo 'The matching runtime commits are installed by .github/workflows/flatpak-release.yml.'
    exit 0
fi
if (( $# > 1 )); then
    echo 'Expected at most one output directory' >&2
    exit 2
fi
root=$(git -C "$(dirname -- "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)
cd "$root"
for command in flatpak python3 git tar; do
    command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
[[ $(uname -m) == x86_64 ]] || { echo 'This beta builds only for x86_64' >&2; exit 1; }
git diff --quiet HEAD -- phimthai packaging pyproject.toml typhoon_backend.py typhoon_service.py scripts README.md LICENSE || {
    echo 'Commit application and packaging changes before building a release' >&2
    exit 1
}
sdk_commit=94e029e5b32c7d8bb1a44ff4492eca273c9886e55e33d7dba273c75e678353ca
runtime_commit=3adaa41de78d95076617f743099ec3851b5ae4fcdadbaaa8b7df1412c705c56c
[[ $(flatpak info --user --show-commit org.kde.Sdk//6.11) == "$sdk_commit" ]] || {
    echo 'KDE SDK commit differs from the verified release toolchain; see flatpak-release.yml' >&2; exit 1;
}
[[ $(flatpak info --user --show-commit org.kde.Platform//6.11) == "$runtime_commit" ]] || {
    echo 'KDE Platform commit differs from the verified release runtime; see flatpak-release.yml' >&2; exit 1;
}
output=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "${1:-dist}")
mkdir -p "$output" "$root/.cache"
work=$(mktemp -d "$root/.cache/release-build.XXXXXX")
trap 'echo "Release build workspace: $work" >&2' EXIT
source_dir="$work/source"
mkdir -p "$source_dir"
git archive HEAD | tar -xf - -C "$source_dir"
release_tag=$(python3 - "$source_dir/pyproject.toml" <<'PY'
import re, sys, tomllib
with open(sys.argv[1], 'rb') as stream:
    version = tomllib.load(stream)['project']['version']
match = re.fullmatch(r'2\.0\.0b([1-9][0-9]*)', version)
if not match:
    raise SystemExit('Expected a PEP 440 beta version such as 2.0.0b1')
print('v2.0.0-beta.' + match[1])
PY
)
if [[ ${GITHUB_REF_TYPE:-} == tag && ${GITHUB_REF_NAME:-} != "$release_tag" ]]; then
    echo 'Git tag and pyproject.toml beta version differ' >&2
    exit 1
fi
if [[ ${GITHUB_REF_NAME:-} == release/* && ${GITHUB_REF_NAME#release/} != "$release_tag" ]]; then
    echo 'Release branch and pyproject.toml beta version differ' >&2
    exit 1
fi
app_id=io.github.tatarus9450.PhimThaiMaiPen
basename="PhimThaiMaiPen-${release_tag#v}-x86_64"
mkdir -p "$source_dir/.cache/flatpak-wheels"
# Pin the complete Python closure, including transitive dependencies. A newly
# introduced dependency must be reviewed and pinned before the build can pass.
cat > "$source_dir/.cache/release-constraints.txt" <<'EOF'
accelerate==1.12.0
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
dbus-next==0.2.3
filelock==3.32.6
fsspec==2026.7.0
hf-xet==1.6.0
huggingface-hub==0.36.2
idna==3.19
jinja2==3.1.6
markupsafe==3.0.3
mpmath==1.3.0
networkx==3.6.1
numpy==2.4.6
openvino==2026.3.1
openvino-genai==2026.3.1.0
openvino-telemetry==2025.2.0
openvino-tokenizers==2026.3.1.0
packaging==26.3
protobuf==7.36.1
psutil==7.2.2
pycparser==3.0
pyside6==6.11.1
pyside6-addons==6.11.1
pyside6-essentials==6.11.1
pyyaml==6.0.3
regex==2026.9.10
requests==2.34.2
safetensors==0.8.0
sentencepiece==0.2.2
setuptools==81.0.0
shiboken6==6.11.1
soundfile==0.14.0
sympy==1.14.0
tokenizers==0.22.2
torch==2.11.0+cpu
tqdm==4.70.1
transformers==4.57.6
typing-extensions==4.16.0
urllib3==2.7.0
webrtcvad-wheels==2.0.14
wheel==0.45.1
EOF

# Resolve in the SDK's real CPython 3.13 environment, never the runner Python.
# Torch uses only the official CPU host and a fixed wheel digest.
flatpak run --user --filesystem="$work" --share=network --command=bash org.kde.Sdk//6.11 -c '
    set -euo pipefail
    cd "$1"
    python3 -c "import sys; assert sys.version_info[:2] == (3, 13)"
    python3 -m pip download --no-deps --dest .cache/flatpak-wheels \
      "https://download.pytorch.org/whl/cpu/torch-2.11.0%2Bcpu-cp313-cp313-manylinux_2_28_x86_64.whl#sha256=45025d7752dbc6b4c784c03afaee9c5f19730ce084b2e43fc9a2fe1677d9ff86"
    python3 -m pip download --only-binary=:all: --index-url https://pypi.org/simple \
      --find-links .cache/flatpak-wheels --dest .cache/flatpak-wheels \
      --constraint .cache/release-constraints.txt --requirement packaging/requirements-local.txt wheel==0.45.1
' _ "$source_dir"

# Verify each downloaded PyPI file against its exact-version upstream digest,
# and retain its source URL + hash with the public release for reproduction.
python3 - "$source_dir" "$output/$basename-wheels.json" <<'PY'
import email, hashlib, json, pathlib, re, sys, urllib.request, zipfile
root, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
normalize = lambda value: re.sub(r'[-_.]+', '-', value).lower()
pins = dict(line.split('==') for line in (root / '.cache/release-constraints.txt').read_text().splitlines())
records = []
for wheel in sorted((root / '.cache/flatpak-wheels').glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        # setuptools contains vendored distributions with their own metadata.
        # Only the wheel's top-level dist-info describes the downloaded package.
        metadata_paths = [name for name in archive.namelist()
                          if name.count('/') == 1 and name.endswith('.dist-info/METADATA')]
        if len(metadata_paths) != 1:
            raise SystemExit('Ambiguous wheel metadata: ' + wheel.name)
        metadata = email.message_from_bytes(archive.read(metadata_paths[0]))
    name, version = normalize(metadata['Name']), metadata['Version']
    if pins.get(name) != version:
        raise SystemExit('Unpinned or unexpected dependency: ' + name + '==' + version)
    with wheel.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if name == 'torch':
        expected = '45025d7752dbc6b4c784c03afaee9c5f19730ce084b2e43fc9a2fe1677d9ff86'
        url = 'https://download.pytorch.org/whl/cpu/' + wheel.name.replace('+', '%2B')
    else:
        request = urllib.request.Request(f'https://pypi.org/pypi/{name}/{version}/json',
                                         headers={'User-Agent': 'PhimThaiMaiPen-release-builder'})
        with urllib.request.urlopen(request, timeout=60) as response:
            release = json.load(response)
        matches = [item for item in release['urls'] if item['filename'] == wheel.name]
        if len(matches) != 1:
            raise SystemExit('Wheel absent from its pinned upstream release: ' + wheel.name)
        expected, url = matches[0]['digests']['sha256'], matches[0]['url']
    if digest != expected:
        raise SystemExit('Upstream wheel checksum mismatch: ' + wheel.name)
    records.append(dict(name=name, version=version, filename=wheel.name, url=url, sha256=digest))
target.write_text(json.dumps(records, indent=2) + '\n')
PY

python3 "$source_dir/scripts/prepare-local-flatpak.py"
manifest="$source_dir/.cache/$app_id.local.json"
flatpak run --user --filesystem="$work" org.flatpak.Builder --user \
    --disable-rofiles-fuse --state-dir="$work/builder-state" --jobs=2 --force-clean \
    --repo="$work/repo" "$work/build" "$manifest"

# The runtime (not SDK) must import the installed inference and GUI graph.
# No model download, microphone, output audio, window or clipboard access.
flatpak build --runtime --readonly --unshare=network \
    --nosocket=wayland --nosocket=x11 --nosocket=pulseaudio \
    --env=QT_QPA_PLATFORM=offscreen --env=PYTHONPATH=/app/lib/python3.13/site-packages \
    --env=HF_HUB_OFFLINE=1 --env=TRANSFORMERS_OFFLINE=1 \
    "$work/build" python3 -c '
import importlib.metadata as metadata, json, pathlib
import torch, PySide6
from qwen_asr import Qwen3ASRModel
from transformers import MarianMTModel, MarianTokenizer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import QApplication
from phimthai.settings import Settings
from phimthai.feedback import DictationFeedback
import phimthai.app
settings = Settings()
assert settings.model == "qwen-0.6b" and settings.profile == "smart"
assert torch.__version__ == "2.11.0+cpu" and torch.version.cuda is None
assert PySide6.__version__ == "6.11.1"
assets = pathlib.Path(phimthai.app.__file__).parent / "assets"
assert all((assets / ("feedback-" + name + ".wav")).is_file() for name in ("start", "stop", "mode", "ready"))
application = QApplication([])
feedback = DictationFeedback(sound_enabled=False, popup_enabled=False)
assert not feedback._interactive
feedback.shutdown()
print(json.dumps({"version": metadata.version("phimthai-maipen"), "torch": torch.__version__, "pyside": PySide6.__version__, "default_model": settings.model, "profile": settings.profile, "runtime_imports": "passed", "real_desktop_audio_asr": "not tested by this headless smoke"}))
' > "$output/$basename-smoke.json"

# Exercise the exact packaged worker on pinned public audio, offline. The
# temporary model/data tree remains outside /app and outside release assets.
mkdir -p "$work/test-data" "$work/samples"
flatpak build --runtime --readonly --share=network --filesystem="$work" \
    --nosocket=wayland --nosocket=x11 --nosocket=pulseaudio \
    --env=PYTHONPATH=/app/lib/python3.13/site-packages \
    --env=XDG_DATA_HOME="$work/test-data" --env=HF_HOME="$work/model-cache" \
    --env=HF_HUB_DISABLE_IMPLICIT_TOKEN=1 --env=HF_HUB_DISABLE_TELEMETRY=1 \
    "$work/build" python3 -c 'from phimthai.models import download; download("qwen-0.6b")'
python3 - "$source_dir/scripts/benchmark.py" "$work/samples" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('release_samples', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.fetch_samples(pathlib.Path(sys.argv[2]))
PY
flatpak build --runtime --readonly --unshare=network --filesystem="$work:ro" \
    --nosocket=wayland --nosocket=x11 --nosocket=pulseaudio \
    --env=PYTHONPATH=/app/lib/python3.13/site-packages --env=QT_QPA_PLATFORM=offscreen \
    --env=QT_AUDIO_BACKEND=pulseaudio --env=QT_PLUGIN_PATH=/app/lib/plugins:/usr/lib/plugins \
    "$work/build" python3 "$source_dir/scripts/verify-flatpak-preview.py" \
    --model-dir "$work/test-data/phimthai/models/qwen-0.6b" --samples-dir "$work/samples" \
    --threads 2 > "$output/$basename-asr.json" || { cat "$output/$basename-asr.json"; exit 1; }

flatpak build-bundle --arch=x86_64 \
    --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
    "$work/repo" "$output/$basename.flatpak" "$app_id" beta
# Validate the actual exported bundle can be imported without installing it.
flatpak run --user --filesystem="$work" --command=ostree org.flatpak.Builder \
    --repo="$work/import-check" init --mode=archive-z2
flatpak build-import-bundle "$work/import-check" "$output/$basename.flatpak"
cp "$manifest" "$output/$basename-manifest.json"
cp "$source_dir/.cache/release-constraints.txt" "$output/$basename-constraints.txt"
python3 - "$output" "$basename" "$sdk_commit" "$runtime_commit" "$(git rev-parse HEAD)" <<'PY'
import hashlib, json, pathlib, sys
output, prefix = pathlib.Path(sys.argv[1]), sys.argv[2]
provenance = dict(commit=sys.argv[5], sdk_commit=sys.argv[3], runtime_commit=sys.argv[4],
                  architecture='x86_64', branch='beta', models_bundled=False,
                  dependency_policy='Pinned upstream wheels; source-patched Qt Multimedia and Qwen; not a Flathub submission')
(output / (prefix + '-build.json')).write_text(json.dumps(provenance, indent=2) + '\n')
checksums = []
for path in sorted(output.glob(prefix + '*')):
    if path.name.endswith('.sha256'):
        continue
    if path.stat().st_size >= 2 * 1024**3:
        raise SystemExit('GitHub release asset must be below 2 GiB: ' + path.name)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    # Users download the bundle and SHA256SUMS; auxiliary reports are optional.
    if path.suffix == '.flatpak':
        checksums.append(digest + '  ' + path.name)
(output / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
print('Release assets: ' + str(output))
PY
