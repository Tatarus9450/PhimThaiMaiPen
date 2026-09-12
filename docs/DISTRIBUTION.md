# Flatpak beta distribution

Updated 2026-09-12. Delivery now includes a versioned GitHub source release and a downloadable Flatpak beta. Application ID `io.github.tatarus9450.PhimThaiMaiPen`, branch `beta`, architecture x86_64, KDE Platform/SDK 6.11. The application version is `2.0.0b1`; Git tag `v2.0.0-beta.1`. This direct-download preview is **not published on Flathub**. Discover can install the downloaded bundle; searching Flathub for the application will not find it yet

## Install, update and rollback

Download the `.flatpak` and `SHA256SUMS` from [GitHub Releases](https://github.com/Tatarus9450/PhimThaiMaiPen/releases/tag/v2.0.0-beta.1). Verify with `sha256sum --check SHA256SUMS`, then open the bundle in Discover or run:

```bash
flatpak install --user ./PhimThaiMaiPen-2.0.0-beta.1-x86_64.flatpak
flatpak run --branch=beta io.github.tatarus9450.PhimThaiMaiPen
```

The bundle points to Flathub for the KDE runtime. Runtime dependencies and models download separately. New settings use Qwen3-ASR 0.6B, automatic language/device selection, Smart Mix and review before paste. Qwen's pinned model revision is `5eb144179a02acc5e5ba31e748d22b0cf3e303b0` (~1.89 GB). Allow sufficient RAM for the desktop in addition to the measured 5.3–6 GB ASR peak. Model selection remains available; existing settings are preserved

Start the app, download the model, test the microphone and enable shortcuts/paste in Settings. The desktop must grant portal permissions. Meta+H starts/stops recording; Meta+Shift+H cycles modes. Set immediate paste if desired. XWayland is needed for the small left-side popup on Wayland

Quit before installing an updated bundle. To return to an earlier beta bundle, use `flatpak install --user --reinstall ./earlier-version.flatpak`. Model/config data stays under `~/.var/app/io.github.tatarus9450.PhimThaiMaiPen/`; do not use `--delete-data` during rollback. Direct bundles do not provide an application update remote. Native and Flatpak have separate settings; run only one at a time to avoid competing shortcuts

When migrating from the native KDE installation, quit the native app and release its Meta+H / Meta+Shift+H bindings in KDE System Settings → Keyboard → Shortcuts before enabling the Flatpak bindings. Native launcher shortcuts can remain active even after its window closes. The sandbox obtains its own portal permissions; existing native grants do not prove the Flatpak is authorized

## Local integration package

`scripts/build-release-flatpak.sh` resolves wheels inside the KDE SDK, builds, exports and smoke-tests the beta bundle. GitHub Actions calls the same helper for release tags and attaches the bundle, SHA256 checksums, dependency provenance and verification output. `scripts/prepare-local-flatpak.py` prepares the offline manifest under `.cache/`. It includes wheel dependencies, source-built MIT Kerberos, source-patched Qt Multimedia and the same minimal Qwen source patch used by the native installer. This recipe is for direct GitHub distribution, not the final Flathub source recipe

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
  .cache/flatpak-release-repo dist/PhimThaiMaiPen-2.0.0-beta.1-x86_64.flatpak \
  io.github.tatarus9450.PhimThaiMaiPen beta
```

Models live in the app's XDG data directory, outside installation updates. Their catalog entries pin revisions and verify downloaded contents. Permissions are Wayland, X11 (also under Wayland for the XCB popup), IPC, PulseAudio, network for downloads and `dri` for graphics devices. No unrestricted home or D-Bus access is included. Per-run filesystem access used by test scripts is not part of the package

The public beta uses CPU PyTorch and includes OpenVINO for compatible alternative models. AMD NPU/FastFlowLM and Vulkan experiments are excluded by default. `--experimental-accelerators` opts into locally built artifacts for developers only; `--source-pyside` uses the local source-PySide proof. Neither switch is used by the public release workflow

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
