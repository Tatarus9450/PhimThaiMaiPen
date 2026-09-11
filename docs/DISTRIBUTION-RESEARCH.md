# Flatpak and Flathub distribution

Evidence checked on 2026-09-12. This document describes release gates, not a claim that the application is already available on Flathub. Record subsequent build results in [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Package identity and initial target

- Application ID: `io.github.tatarus9450.PhimThaiMaiPen`.
- Upstream: <https://github.com/Tatarus9450/PhimThaiMaiPen>.
- Initial architecture: `x86_64`; add `flathub.json` with `"only-arches": ["x86_64"]` beside the submission manifest until ARM64 has its own build and runtime evidence.
- Intended runtime: `org.kde.Platform//6.11`, SDK: `org.kde.Sdk//6.11`. Both appeared in the Flathub remote inventory on the evidence date. Match PySide6 to the actual SDK Qt/Python versions; check runtime currency again before submission.
- Download model weights separately after installation. Keep app-owned models, settings and caches in the respective XDG directories so Flatpak's private storage works without home-directory access.

## Source-build gate

Flathub currently requires source-available applications and their runtime dependencies to be built from source. Exceptions are reviewed individually; another application's binary dependency does not grant this application an exception. Build steps have no network access, so every dependency and build tool must be provided as a manifest source beforehand, with pinned revisions or checksums. A local bundle made from downloaded wheels is useful for integration testing but does not satisfy this gate by itself.

Submission also requires the latest available runtime, correct redistribution licenses, complete English UI and metadata, upstream desktop/AppStream/icon files, and a stable release. Required module license files must be installed. Use a reviewed source release or immutable commit for the application rather than an uncommitted local directory. These constraints come from [Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements).

Before submitting this Python application:

1. Resolve the exact dependency graph for the selected ASR/translation backends and Python ABI.
2. Build PySide6/Shiboken against SDK Qt, including the Qt modules used by the UI and microphone capture.
3. Build CPU PyTorch and compiled Python dependencies from pinned sources with all build dependencies available offline. Confirm that the resulting Python `torch` package imports and executes the selected ASR model; a standalone `libtorch` build is insufficient for a Python backend.
4. Build/install the remaining Python packages offline. Runtime downloads must contain model data, not serve as an unreviewed replacement for packaging executable dependencies.
5. Audit third-party licenses and run the clean sandbox checks below. GPU/NPU runtime extensions need their own compatibility and redistribution review.

## Reusable source references

The current [FreeCAD Flathub manifest](https://github.com/flathub/org.freecad.FreeCAD/blob/master/org.freecad.FreeCAD.yaml) contains a PySide source module for KDE 6.11 with the LLVM 21 SDK extension. It uses `cmake-ninja`, PySide 6.11.1, `FORCE_LIMITED_API=OFF` and `SHIBOKEN_FORCE_PROCESS_SYSTEM_INCLUDE_PATHS=/usr/include`. The observed source is [Qt's PySide 6.11.1 archive](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz), SHA-256 `6ffd9835bb0dd2c56f061d62f1616bb1707cfc0202b80e3165d6be087f3965e2`. Its module also references `patches/pyside-fix-header-installation-path.patch` and `patches/pyside-fix-header-packaging.patch`. Inspect these alongside the module before adapting it; FreeCAD-specific paths and cleanup are not automatically suitable here. This reference was read, not built for PhimThaiMaiPen.

The bounded search did **not** identify a reusable Flathub Python PyTorch source-build module. [Speech Note's AMD add-on](https://github.com/flathub/net.mkiol.SpeechNote.Addon.amd/blob/beta/net.mkiol.SpeechNote.Addon.amd.yaml) uses an `apply_extra` installation of Torch wheels. It is a reference for extension structure, not evidence that our source-build gate is satisfied. The [Speech Note application manifest](https://github.com/flathub/net.mkiol.SpeechNote/blob/master/net.mkiol.SpeechNote.yaml) likewise illustrates separate CPU/GPU Python paths; do not copy its broad permissions or older runtime without assessing this app's needs.

### Python 3.13 and an actionable CPU source-build path

The KDE 6.11 SDK is now installed; the observed SDK commit is `94e029e5b32c7d8bb1a44ff4492eca273c9886e55e33d7dba273c75e678353ca`. The application team's SDK probe reports Python 3.13.13. Python 3.13 is not itself a PyTorch blocker: the official [CPU wheel index](https://download.pytorch.org/whl/cpu/torch/) lists `torch-2.11.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl`, SHA-256 `45025d7752dbc6b4c784c03afaee9c5f19730ce084b2e43fc9a2fe1677d9ff86`. A direct HEAD request to the index's `download-r2.pytorch.org` URL returned HTTP 403 during this investigation. This confirms a published ABI target, not a completed download, source build or ASR test.

Recommended submission route: build CPU PyTorch in a separate dependency module, then build the application against that module. Keep the wheel-based experimental package as the desktop-integration test vehicle. A CPU source build is technically plausible from the published upstream prerequisites, but its offline completion, memory use and inference performance remain unmeasured.

Use the following verified source identities as the start of a dependency lock, not as a complete manifest:

| Component | Exact source | Pin |
| --- | --- | --- |
| PyTorch 2.11.0 | [Git repository](https://github.com/pytorch/pytorch.git) | Tag `v2.11.0`, commit `70d99e998b4955e0049d13a98d77ae1b14db1f45`; retain recursive submodules |
| PySide6 6.11.1 | [Qt source archive](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz) | SHA-256 `6ffd9835bb0dd2c56f061d62f1616bb1707cfc0202b80e3165d6be087f3965e2` |
| qwen-asr 0.0.6 | [Source distribution](https://files.pythonhosted.org/packages/7f/5b/56c5175d1a4d6ed8602003385570304305e4ae9c40b999d12d75a70c0561/qwen_asr-0.0.6.tar.gz) | SHA-256 `294893f2340dc2d58d1f1d1cb8ce26ac0a79f254805ab432dda2892bd5c8d13c` |
| Transformers 4.57.6 | [Source distribution](https://files.pythonhosted.org/packages/c4/35/67252acc1b929dc88b6602e8c4a982e64f31e733b804c14bc24b47da35e6/transformers-4.57.6.tar.gz) | SHA-256 `55e44126ece9dc0a291521b7e5492b572e6ef2766338a610b9ab5afbb70689d3` |
| Accelerate 1.12.0 | [Source distribution](https://files.pythonhosted.org/packages/4a/8e/ac2a9566747a93f8be36ee08532eb0160558b07630a081a6056a9f89bf1d/accelerate-1.12.0.tar.gz) | SHA-256 `70988c352feb481887077d2ab845125024b2a137a5090d6d7a32b57d03a45df6` |

PyTorch's pinned [build metadata](https://github.com/pytorch/pytorch/blob/v2.11.0/pyproject.toml) names `setuptools>=70.1.0,<82`, `cmake>=3.27`, `ninja`, `numpy`, `packaging`, `pyyaml`, `requests`, `six` and `typing-extensions>=4.10.0`. Its [README](https://github.com/pytorch/pytorch/blob/v2.11.0/README.md) requires Python >=3.10 and a C++17 compiler. The pinned `.gitmodules` has 37 direct entries; a GitHub archive alone omits this recursive source graph. Fetch everything before the offline build phase.

Candidate CPU configuration, based on the pinned [setup.py](https://github.com/pytorch/pytorch/blob/v2.11.0/setup.py) and [CMake options](https://github.com/pytorch/pytorch/blob/v2.11.0/CMakeLists.txt): `USE_CUDA=0`, `USE_ROCM=0`, `USE_XPU=0`, `BUILD_TEST=0`, `USE_DISTRIBUTED=0`, `MAX_JOBS=2`. Package a compatible BLAS implementation and retain CPU kernels needed for acceptable inference performance. Limit compile parallelism initially, then measure. Install the Python package with `python3 -m pip install --no-index --no-deps --no-build-isolation --prefix=/app .` after provisioning its build/runtime dependencies. These options are a proposed experiment; especially verify that disabling distributed support does not break Accelerate imports.

The source-build closure extends beyond Torch: the existing environment contains NumPy 2.4.6, SciPy 1.17.1, tokenizers 0.22.2, safetensors 0.8.0, sentencepiece 0.2.2, librosa 0.11.0, Numba 0.67.0, llvmlite 0.49.0, soxr 1.1.0 and soundfile 0.14.0. PyPI source distributions were confirmed for these versions. Their compilers, build backends, native libraries and Rust/LLVM dependencies still need an offline source manifest and Python 3.13 verification; local Python 3.11 package versions are not proof of SDK compatibility.

Qwen 0.0.6 also pins `nagisa==0.2.11` and imports its forced-aligner module eagerly from `qwen_asr/__init__.py`; that module imports `nagisa` at top level. Nagisa depends on DyNet38. The Qwen source package itself builds with `setuptools>=68` and `wheel`; its metadata also declares demo/web dependencies. Any reduced dependency set needs explicit import and feature coverage rather than relying on `--no-deps` to conceal missing packages.

### Minimal ASR-only Qwen dependency patch

An AST import scan of the installed Qwen 0.0.6 package found one small change sufficient to remove the eager Nagisa dependency: in `qwen_asr/inference/qwen3_forced_aligner.py`, remove the top-level `import nagisa` at line 21 and import it inside `Qwen3ForceAlignProcessor.tokenize_japanese`, immediately before `words = nagisa.tagging(text).words` at line 102. Leave the package exports, constructor annotations and forced-aligner API intact. Korean `soynlp` is already imported inside its specific language branch. Preserve the upstream Apache-2.0 notice and carry the patch explicitly in packaging.

A fresh Python 3.11 subprocess applied this change only in memory while blocking imports of `nagisa`, `dynet`, `_dynet`, `DyNet38`, `flask`, `gradio`, `soynlp`, `sox`, `qwen_omni_utils` and `pytz`. Importing both `Qwen3ASRModel` and `Qwen3ForcedAligner` succeeded without loading any blocked module. This is import evidence only. Real Thai/English inference under SDK Python 3.13, optional-feature failure behavior and installed-package metadata still need verification.

The direct roots for the app's Transformers ASR path are `torch`, `transformers==4.57.6`, `accelerate==1.12.0`, `numpy`, `librosa` and `soundfile`, plus Qwen itself. The import scan found no demo/web/SoX/Qwen-Omni imports in that path. Install sentencepiece separately for the application's translation backend. If shipping this reduced variant, adjust upstream dependency metadata in the source patch to describe the supported ASR subset and optional features accurately; blindly ignoring declared requirements would make `pip check` misleading.

Resolve the complete transitive graph in Python 3.13 before locking. The local metadata graph includes Torch's filelock/typing-extensions/setuptools/sympy/networkx/jinja2/fsspec dependencies; Transformers adds huggingface-hub, packaging, pyyaml, regex, requests, tokenizers, safetensors and tqdm; Accelerate adds psutil. Librosa adds audioread, Numba/llvmlite, SciPy, scikit-learn, joblib, decorator, pooch, soxr, lazy-loader and msgpack. Soundfile requires CFFI plus a usable libsndfile. Huggingface-hub's declared platform dependencies include hf-xet. Each of those has further dependencies; this paragraph is an inventory, not a substitute for a resolver-generated lock.

Python 3.13 additionally selects `standard-aifc` and `standard-sunau` through Librosa/audioread. Current source metadata for version 3.13.0 requires `standard-chunk` and `audioop-lts` transitively. These were absent from the original Python 3.11 inventory; include them in SDK resolution. See the authoritative package metadata for [standard-aifc](https://pypi.org/pypi/standard-aifc/3.13.0/json), [standard-sunau](https://pypi.org/pypi/standard-sunau/3.13.0/json) and [standard-chunk](https://pypi.org/pypi/standard-chunk/3.13.0/json).

For the experimental wheel package, installed PySide6 6.11.2 distribution metadata places `QtMultimedia.abi3.so` and `QtMultimediaWidgets.abi3.so` in **PySide6_Addons**, not Essentials. Include Addons when using `QAudioSource`/`QMediaDevices`; a later source build can select the actual Qt modules the application needs.

### Wheel-based Qt multimedia: Kerberos loader dependency

The experimental Flatpak was subsequently built and installed, but its first smoke test failed loading `PySide6.QtMultimedia`. Read-only `ldd` checks inside that installed sandbox examined 27 relevant Qt Python modules and platform/multimedia/TLS/input plugins. The only unresolved SONAME in that set was `libgssapi_krb5.so.2`, required through the wheel's bundled `libQt6Network.so.6`. Six checked objects were affected, including `QtMultimedia.abi3.so`, the FFmpeg multimedia plugin and both TLS plugins. This is a binary loader dependency even when the app is not using Kerberos authentication.

The [Flathub Zoom manifest](https://github.com/flathub/us.zoom.Zoom/blob/master/us.zoom.Zoom.json) supplies a small reusable source module. Place it before the Python/wheel modules in the local manifest:

```yaml
- name: krb5
  buildsystem: autotools
  subdir: src
  config-opts:
    - --disable-static
    - --disable-rpath
    - --without-keyutils
    - --without-libedit
  sources:
    - type: archive
      url: https://kerberos.org/dist/krb5/1.22/krb5-1.22.2.tar.gz
      sha256: 3243ffbc8ea4d4ac22ddc7dd2a1dc54c57874c40648b60ff97009763554eaf13
```

The first two configure options come from the existing Flathub module. The optional-library exclusions are supported by this archive's `src/configure.ac` and reduce unnecessary dependency detection for the proposed build. The official archive was downloaded into memory (8,747,729 bytes); its SHA-256 matched the manifest, and it contains a generated `src/configure`. No additional source module was shown necessary by the initial 27-object loader scan. This recipe has not been built by the investigation; verify the produced Kerberos libraries' own dependency closure after building. Preserve shared libraries and license notices when removing development tools or headers.

After rebuilding, repeat `ldd` inside the installed app, import `PySide6.QtMultimedia` and the other UI modules, then test actual microphone capture and plugin loading. Fixing this loader dependency does not prove the complete app smoke test or audio path succeeds, and does not change the outstanding PySide/PyTorch source-build gate for Flathub.

### What the Speech Note precedent permits us to conclude

The pinned [Speech Note CPU module](https://github.com/flathub/net.mkiol.SpeechNote/blob/77a7b501fffa9cf672971574a718177a21ca7cd4/python3-modules-x86-64.yaml#L50) installs PyTorch/TorchAudio 2.5.1 CPU wheels offline under `/app/extensions/cpu`. Its [AMD beta add-on](https://github.com/flathub/net.mkiol.SpeechNote.Addon.amd/blob/beta/net.mkiol.SpeechNote.Addon.amd.yaml) now describes CPython 3.13 wheels as `extra-data`, unpacks them during installation, and exposes them through extension Python paths. These are concrete packaging mechanisms, not source-build recipes.

An `extra-data` variant is a possible review proposal if a documented source-build attempt fails or proves unsuitable. Pin each vendor URL, download size and checksum, include the installation script and license notices, and present the reason to Flathub. Do not treat moving a source-available binary into `extra-data` as an automatic exemption from the source-build rule. No exemption has been requested or granted for PhimThaiMaiPen. Continue source-build preparation while the experimental local bundle validates the UI and sandbox integration.

## Sandbox permissions and desktop integration

The intended baseline is:

```yaml
finish-args:
  - --socket=wayland
  - --socket=fallback-x11
  - --share=ipc
  - --socket=pulseaudio
  - --env=QT_AUDIO_BACKEND=pulseaudio
  - --share=network
  - --device=dri
```

The display permissions support native Wayland with X11 fallback. PulseAudio access includes microphone capture and works with compatible host audio services. Network is needed for model downloads; cached inference must be tested with network unavailable. `dri` supplies graphics device access but does not prove that a particular ASR GPU runtime works. Avoid host/home filesystem access and unrestricted session/system bus access. See [Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

After Kerberos was added, read-only audio enumeration in the installed experimental app found three inputs with the same IDs/default device as native execution. Without the audio environment setting, Qt also logged `Failed to connect to pipewire instance "Host is down"`; enumeration still succeeded through fallback. Running the same probe with `QT_AUDIO_BACKEND=pulseaudio` preserved all three devices and removed that error. No microphone stream was opened. Qt 6.11.2's [audio-device factory](https://github.com/qt/qtmultimedia/blob/v6.11.2/src/multimedia/platform/qplatformaudiodevices.cpp#L54) reads this variable and skips the PipeWire attempt when it is set to `pulseaudio`, then selects compiled PulseAudio support. Use this setting with the existing PulseAudio socket permission; direct PipeWire filesystem access is not needed for this route. Device enumeration is not a recording-quality test.

Use [Global Shortcuts](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html) sessions for hotkeys and show the portal's actual configured triggers. The observed host exposes version 2, including `ConfigureShortcuts`; this is host introspection evidence, not a sandbox shortcut test.

Automatic key injection needs a separately granted [Remote Desktop](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html) keyboard session. The observed host exposes version 2 and device mask 7. A successful key-injection call is not an acknowledgment that the destination pasted the text. Clipboard preservation, focus handling and manual-copy fallback need application-level tests. Portal availability on this KDE host does not establish GNOME or other desktop compatibility.

## NPU boundary

The host exposes `/dev/accel/accel0`, but no sandbox ASR run has been established by this distribution investigation. Current documented Flatpak device permissions are `dri`, `input`, `usb`, `kvm`, `shm` and `all`; there is no dedicated `accel` permission. `/dev` is reserved, so `--filesystem=/dev/accel` does not provide the required access. `--device=all` may expose the device for a local experiment, but it is broader than the baseline and requires separate justification before distribution. It does not supply the host driver or vendor runtime. See [Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html) and [sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

Keep NPU status experimental until the exact model, runtime, kernel driver and sandbox configuration complete real transcription. Record which operators execute on NPU, warm/cold timing, accuracy and CPU fallback. Intel hardware testing remains a separate gate; AMD device detection cannot satisfy it.

## Acceptance states

| Stage | Evidence required | State from this investigation |
| --- | --- | --- |
| Host prerequisites | Flatpak, usable remote and candidate runtime inventory | Observed: Flatpak 1.18.2 and Flathub; KDE SDK 6.11 subsequently installed |
| Local package | Clean build, installation and app launch | Experimental wheel bundle built/installed; initial Kerberos loader failure corrected; main execution reports smoke exit 0 |
| Core sandbox behavior | Real mic recording, model download, cached ASR, editor, clipboard and shortcuts | Not established here |
| Source-build compliance | Offline source build and third-party license audit | Pending |
| Cross-desktop support | Distro/desktop/session-specific end-to-end results | Pending |
| GPU/NPU support | Real inference on the published hardware/runtime combinations | Pending |
| Submission ready | Stable upstream release, AppStream/assets, clean builder and linter output | Pending |
| Flathub accepted | Maintainer review and published Flathub build | External gate; not accepted |
| Discover visible | Accepted app appears through an enabled Flathub remote | Not established |

The absence of a failed test is not a pass. Do not promote any row using unit tests, host-only execution or mock hardware results.

## Build and submission verification

With `org.flatpak.Builder` and the required SDK available, use the official builder workflow. Replace `PATH_TO_MANIFEST` with the actual manifest; these are instructions, not recorded successful executions:

```bash
flatpak run --command=flathub-build org.flatpak.Builder --install PATH_TO_MANIFEST
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest PATH_TO_MANIFEST
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
flatpak run io.github.tatarus9450.PhimThaiMaiPen
```

Test fresh per-app data, interrupted/resumed model downloads, offline use after download, cancellation, worker failure, microphone removal, clipboard changes during processing, settings persistence, update and rollback. Record build/runtime versions and actual results in the execution ledger. Preserve user data during uninstall and rollback testing.

Flathub submissions use the `new-pr` branch, followed by external review. Keep application sources and metadata upstream; submit packaging files in the form Flathub requests. A locally installed Flatpak or a submission PR does not mean a searchable Flathub release exists. See the official [submission workflow](https://docs.flathub.org/docs/for-app-authors/submission).
