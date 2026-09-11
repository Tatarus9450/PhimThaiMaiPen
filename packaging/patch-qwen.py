"""Keep unused Japanese alignment and alternate audio loaders lazy in Qwen 0.0.6."""
import importlib.util
from pathlib import Path

spec = importlib.util.find_spec("qwen_asr")
path = Path(spec.origin).parent / "inference/qwen3_forced_aligner.py"
source = path.read_text()
if "\nimport nagisa\n" not in source:
    raise SystemExit("Unexpected Qwen source: review the compatibility patch")
source = source.replace("\nimport nagisa\n", "\n", 1)
needle = "        words = nagisa.tagging(text).words"
if source.count(needle) != 1:
    raise SystemExit("Unexpected Qwen tokenizer: review the compatibility patch")
source = source.replace(needle, "        import nagisa\n" + needle, 1)
path.write_text(source)

# The app supplies mono 16 kHz numpy audio. Optional file loading/resampling
# still works when callers install Librosa, without importing it for this path.
path = Path(spec.origin).parent / "inference/utils.py"
source = path.read_text()
if source.count("\nimport librosa\n") != 1:
    raise SystemExit("Unexpected Qwen audio imports: review the compatibility patch")
source = source.replace("\nimport librosa\n", "\n", 1)
lines = source.splitlines(keepends=True)
patched = []
count = 0
for line in lines:
    if "librosa.load(" in line or "librosa.resample(" in line:
        patched.append(line[:len(line) - len(line.lstrip())] + "import librosa\n")
        count += 1
    patched.append(line)
if count != 2:
    raise SystemExit("Unexpected Qwen audio loader: review the compatibility patch")
path.write_text("".join(patched))
