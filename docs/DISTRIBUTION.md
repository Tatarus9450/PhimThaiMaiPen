# Packaging experiments — deferred

Updated 2026-09-12. The user narrowed delivery to the native application and GitHub source publication. **Do not continue source-only packaging or submit to Flathub for this delivery.** The notes below preserve completed experiments and possible future work. Application ID `io.github.tatarus9450.PhimThaiMaiPen`, upstream <https://github.com/Tatarus9450/PhimThaiMaiPen>, initial architecture x86_64, KDE Platform/SDK 6.11. This is a development preview installed locally. It is **not published on Flathub**, and is not searchable from Discover through Flathub yet

## Local integration package

`scripts/prepare-local-flatpak.py` prepares the experimental manifest under `.cache/`. It includes the application, pinned wheel dependencies, source-built MIT Kerberos, source-patched Qt Multimedia and locally verified accelerator runtimes. The wheel/local-directory recipe is deliberately identified as an integration package; it is not the final Flathub source recipe

```bash
.venv/bin/python scripts/prepare-local-flatpak.py
flatpak run org.flatpak.Builder --user --install --force-clean \
  .cache/flatpak-build .cache/io.github.tatarus9450.PhimThaiMaiPen.local.json
flatpak run io.github.tatarus9450.PhimThaiMaiPen
```

Models live in the app's XDG data directory, outside installation updates. Their catalog entries pin revisions and verify downloaded contents. Default permissions are Wayland, fallback X11, IPC, PulseAudio, network for downloads and `dri` for graphics devices. No unrestricted home or D-Bus access is included. Per-run filesystem access used by test scripts is not part of the package

## Verified integration

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

## Remaining release acceptance

1. Finish source dependency/runtime closure and preserve all corresponding license notices
2. Run the clean offline source build, installed model/audio/desktop regression checks, Flatpak manifest/repository lint and AppStream/desktop validation
3. Finish representative accuracy/performance and stability tests, including physical microphones, cross-application paste, crash/fallback and supported distro/desktop/session combinations
4. Produce a reviewable versioned upstream release, distributable bundle, update/rollback evidence and user documentation
5. Authenticate to GitHub and follow the official [Flathub submission process](https://docs.flathub.org/docs/for-app-authors/submission). No submission or publication has occurred
6. Verify the accepted package appears in Discover when Flathub is enabled. Local installation and a submission PR alone do not establish this

Keep model/user data during package rollback. Never restore an old checkout by deleting current user changes. The pre-upgrade source/config backup is documented in the execution ledger
