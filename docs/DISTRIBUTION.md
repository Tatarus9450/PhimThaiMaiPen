# Flatpak beta distribution

Updated 2026-10-23 for `2.0.0b6` (tag `v2.0.0-beta.6`). Application ID `io.github.tatarus9450.PhimThaiMaiPen`, branch `beta`, x86_64, KDE Platform/SDK 6.11. Betas are published as GitHub pre-releases after the CI build, offline ASR smoke and bundle import checks pass. The app is **not on Flathub yet**; Discover can install a downloaded bundle but cannot find it by search.

New installations default to Typhoon ASR Realtime (~462 MB, downloaded on first run); Qwen3-ASR models are optional downloads. The bundle includes wl-clipboard (`wl-copy`/`wl-paste` in `/app/bin`) for the Wayland paste fallback. Historical beta 3 publication evidence: [github-beta3-release.json](evidence/github-beta3-release.json).

## Recommended distribution channels

| Channel | Recommendation | Why |
| --- | --- | --- |
| **Flatpak (Flathub)** | **Primary** | Works on Fedora, KDE neon, Ubuntu and others; sandboxed app ID gives proper portal identity for GlobalShortcuts and RemoteDesktop; Discover/GNOME Software integration and automatic updates once on Flathub |
| Native installer (`scripts/install-app.py`) | Developers only | Editable checkout, CUDA/ROCm experiments, direct KDE shortcut binding; no auto-update |
| Fedora COPR RPM | Optional, later | For GPU/NPU power users who need host drivers and system Python stacks; not before the Flatpak is stable |
| Snap | Not recommended | Fedora does not ship snapd; KDE portal integration and GlobalShortcuts support for snaps is less mature; squashfs mount adds startup cost to an app whose value is fast dictation |
| AppImage / standalone binary | Not recommended as primary | 2+ GB with PyTorch; FUSE 2 is absent on Fedora 44 by default; no built-in update channel; unsandboxed apps have no app ID, so the GlobalShortcuts/RemoteDesktop portals identify and remember them poorly |

Do not install more than one copy. A user and a system Flatpak (or Flatpak plus native) register the same Meta+H shortcut twice. Check with `flatpak list --app | grep -i phimthai` and remove the extra one, for example `flatpak uninstall --system io.github.tatarus9450.PhimThaiMaiPen`.

## Roadmap

1. **Auto-updates:** move from downloadable `.flatpak` bundles to Flathub, or in the meantime an OSTree repo with a `.flatpakrepo`/`.flatpakref`, so `flatpak update` and Discover deliver new betas.
2. **Smaller install:** split optional backends (Qwen runtime, Whisper Vulkan, OpenVINO) into Flatpak extensions so the default Typhoon install shrinks from ~2.7 GB.
3. **Drop the X11 socket:** replace the XCB/XWayland dictation popup with a LayerShellQt overlay, then remove `--socket=x11`.
4. Finish the Flathub source-build closure (see below).

## Install, update and rollback

Download `PhimThaiMaiPen-<version>-x86_64.flatpak` and `SHA256SUMS` from the newest pre-release on [GitHub Releases](https://github.com/Tatarus9450/PhimThaiMaiPen/releases). Verify with `sha256sum --check --ignore-missing SHA256SUMS`, then open the bundle in Discover or run:

```bash
flatpak install --user ./PhimThaiMaiPen-*-x86_64.flatpak
flatpak run --branch=beta io.github.tatarus9450.PhimThaiMaiPen
```

The bundle points to Flathub for the KDE runtime. Models download separately into the app's data directory. New installations use Typhoon ASR Realtime, Smart Mix, Auto processing on CPU and immediate paste after desktop permission is granted. Optional Qwen3-ASR 0.6B (pinned revision `5eb144179a02acc5e5ba31e748d22b0cf3e303b0`, ~1.89 GB) needs roughly 5.3–6 GB RAM at peak on CPU. Upgrades preserve existing model, paste and permission settings

The first-run wizard downloads Typhoon (pause/resume supported), selects the microphone and prepares Meta+H (record) and Meta+Shift+H (mode). The user must answer the real desktop consent dialogs for GlobalShortcuts and RemoteDesktop. The ASR worker stays loaded between dictations and is released after 5 idle minutes. XWayland is needed for the left-side popup on Wayland

Logs: `~/.var/app/io.github.tatarus9450.PhimThaiMaiPen/.local/state/phimthai/logs/phimthai.log` (Flatpak maps `XDG_STATE_HOME` to `~/.var/app/<app-id>/.local/state` since Flatpak 1.13)

Existing installations are not treated as first launches: upgrades do not change paste mode, redownload a model the user removed, or repeat initial permission setup automatically. Remembered sessions may still be restored and the desktop may ask for consent again. Denied or unsupported permissions leave editing and manual copy available; retry from Settings

The model manager can import folders containing Qwen3-ASR SafeTensors, Whisper OpenVINO, or Whisper Turbo GGML Q5 in the layouts supported by the existing backends. Import copies and verifies model data while preserving the original folder. It does not execute external model code, accept arbitrary architectures, or install missing runtimes. Qwen pickle weights are unsupported; GGML Turbo Q5 still requires the separate whisper.cpp runtime. Models retain their upstream licenses

Quit before installing an updated bundle. To return to an earlier beta bundle, use `flatpak install --user --reinstall ./earlier-version.flatpak`. Model/config data stays under `~/.var/app/io.github.tatarus9450.PhimThaiMaiPen/`; do not use `--delete-data` during rollback. Direct bundles do not provide an application update remote. Native and Flatpak have separate settings; run only one at a time to avoid competing shortcuts

When migrating from the native KDE installation, quit the native app and release its Meta+H / Meta+Shift+H bindings in KDE System Settings → Keyboard → Shortcuts before enabling the Flatpak bindings. Native launcher shortcuts can remain active even after its window closes. The sandbox obtains its own portal permissions; existing native grants do not prove the Flatpak is authorized

## Local integration package

`scripts/build-release-flatpak.sh` resolves wheels inside the KDE SDK, builds, exports and smoke-tests the beta bundle. GitHub Actions calls the same helper for release tags and attaches the bundle, SHA256 checksums, dependency provenance and verification output. `scripts/prepare-local-flatpak.py` prepares the offline manifest under `.cache/`. It includes wheel dependencies, source-built MIT Kerberos, source-patched Qt Multimedia, wl-clipboard 2.2.1 built with meson from a checksum-pinned release tarball (`packaging/wl-clipboard.json`) and the same minimal Qwen source patch used by the native installer. This recipe is for direct GitHub distribution, not the final Flathub source recipe

```bash
# Clean release build (Flatpak, Builder and KDE SDK required)
bash scripts/build-release-flatpak.sh

# Reuse wheels already resolved in the KDE SDK
python3 scripts/prepare-local-flatpak.py
flatpak run org.flatpak.Builder --user --force-clean \
  --repo=.cache/flatpak-release-repo .cache/flatpak-release-build \
  .cache/io.github.tatarus9450.PhimThaiMaiPen.local.json
mkdir -p dist
flatpak build-bundle --arch=x86_64 \
  --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  .cache/flatpak-release-repo dist/PhimThaiMaiPen-2.0.0-beta.6-x86_64.flatpak \
  io.github.tatarus9450.PhimThaiMaiPen beta
```

Models live in the app's XDG data directory, outside installation updates. Their catalog entries pin revisions and verify downloaded contents. Permissions are Wayland, X11 (kept under Wayland because the dictation popup is an XCB/XWayland window that can be positioned without taking focus; see Roadmap), IPC, PulseAudio, network for downloads and `dri` for graphics devices. No unrestricted home or D-Bus access is included. Per-run filesystem access used by test scripts is not part of the package

The public beta uses CPU PyTorch and includes OpenVINO for compatible alternative models. **Auto stays on CPU.** GPU and NPU options show a red **Beta** warning; they remain under development and CPU is recommended for ordinary dictation. AMD NPU/FastFlowLM and Vulkan experiments are excluded by default. `--experimental-accelerators` opts into locally built artifacts for developers only; `--source-pyside` uses the local source-PySide proof. Neither switch is used by the public release workflow

## Historical integration evidence

| Behavior | Evidence and limits |
| --- | --- |
| Installed GUI and models | App launch and cached Qwen CPU ASR passed; Librosa/Numba/SciPy removed from the installed inference graph |
| Offline ASR | Qwen CPU, patched AMD NPU and Radeon Vulkan ASR run with networking disabled |
| Audio | Patched Qt 6.11.1 records an owned virtual microphone; removal stops capture rather than silently moving to another source |
| Model resume | Actual interrupted HTTP download resumed with Range/206; all final hashes passed |
| Desktop permissions | User granted keyboard access; actual paste into an owned Qt field worked once; Meta+H emitted actual portal activation events |
| Clipboard | All original text/HTML/MIME payloads restored; newer copies preserved. Qt adds a UTF-8 text alias, so format-set identity alone is not the acceptance criterion |
| AMD NPU | Real model inference needs per-run `--device=all`; default permissions cannot access the accelerator and produce one CPU fallback result |
| Radeon GPU | Whisper.cpp Vulkan accesses Radeon 840M in the default `dri` sandbox; eight public clips plus a repeat passed. Portable baseline/Haswell dispatch replaced the slow scalar fallback; installed-worker CPU fallback passed at 23.30 s for a 7.2 s clip (six threads), with one result and server cleanup |

Evidence is in [the execution ledger](IMPLEMENTATION.md), [hardware report](HARDWARE.md), [compatibility matrix](COMPATIBILITY.md), and `evidence/`. These checks do not certify physical microphones, every destination app, all Linux distributions, Intel hardware, or complete 100-cycle recording/paste operation

## Source build progress

[Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements) require source-available code and dependencies to be built from source. Build steps run offline, so dependency sources and build tools must be supplied with immutable pins/checksums. Another application's binary exception does not automatically apply to this application

- PySide/Shiboken 6.11.1 source build passed against SDK Qt; runtime-only imports and Thai/English widgets passed without the SDK/LLVM extension. The reusable recipe and source-derived distribution metadata are being finalized
- Qt Multimedia 6.11.1 source patch fixes PulseAudio removal notifications and prevents automatic input rerouting; installed capture/removal tests passed
- Whisper.cpp 1.9.4 source Vulkan build passed. Portable baseline/Haswell CPU dispatch and installed-worker fallback passed
- Patched FastFlowLM orchestration builds in the SDK and runs actual NPU ASR. Vendor kernel binaries, host driver requirements and accelerator permissions need separate release review
- NumPy, OpenBLAS and Torch build prerequisites have source proofs. Python PyTorch 2.11.0 compilation was stopped after the scope change; cached partial compilation is not an import or ASR pass
- Small Python modules and Rust tokenizers/safetensors have offline source proofs. Full dependency composition, final offline source-only build and OpenVINO runtime packaging are deferred

Exact source pins, source availability and historical investigation are in [SOURCE_BUILD_MATRIX.md](SOURCE_BUILD_MATRIX.md) and [DISTRIBUTION-RESEARCH.md](DISTRIBUTION-RESEARCH.md). The latter records earlier findings; this document and the ledger describe current observed status

## Desktop and accelerator boundaries

The application uses [Global Shortcuts](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html) and [Remote Desktop keyboard sessions](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html). The user controls permission grants. Optional persistence uses the portal's one-use restore token; the desktop can decline persistence or ask again. Key delivery is not proof that an arbitrary target consumed a paste

Current documented [Flatpak permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html) have no dedicated accelerator-only `accel` permission. `--device=all` is broader than the standard app needs and stays outside the default package. It does not install a host driver or guarantee working ASR. A distributable NPU route needs explicit permission/runtime review; the app must retain a self-contained CPU route

## Remaining Flathub acceptance

1. Finish source dependency/runtime closure and preserve all corresponding license notices
2. Run the clean offline source build, installed model/audio/desktop regression checks, Flatpak manifest/repository lint and AppStream/desktop validation
3. Finish representative accuracy/performance and stability tests, including physical microphones, cross-application paste, crash/fallback and supported distro/desktop/session combinations
4. Produce a reviewable versioned upstream release, distributable bundle, update/rollback evidence and user documentation
5. Authenticate to GitHub and follow the official [Flathub submission process](https://docs.flathub.org/docs/for-app-authors/submission). No submission or publication has occurred
6. Verify the accepted package appears in Discover when Flathub is enabled. Local installation and a submission PR alone do not establish this

Keep model/user data during package rollback. Never restore an old checkout by deleting current user changes. The pre-upgrade source/config backup is documented in the execution ledger
