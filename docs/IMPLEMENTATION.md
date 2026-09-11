# PhimThaiMaiPen 2.0 execution ledger

User scope updated 2026-09-12: finish the application, README and .gitignore, then publish the repository to GitHub using SSH as Tatarus9450. Flathub/Discover submission and source-only packaging are deferred. Implemented behavior and observed evidence remain separate from broader hardware certification

## Architecture

`phimthai/` contains a native Qt application and parent-owned JSON worker. Models/settings use XDG directories. Qwen/Marian reuse the corrected legacy inference layer; OpenVINO, FastFlowLM and whisper.cpp Vulkan are separate backends. Unique job IDs, temporary directories and Unix process groups isolate work. The legacy CLI remains available during migration

INTENT: replace the shared-temporary-file/hardcoded-model workflow with the user-approved editable app, reliable lifecycle, selectable models and verified device support. Pre-existing user edits were preserved

## Implemented locally

- [x] Source/config backup: `/home/task/Documents/PhimThaiMaiPen-backups/pre-v2-20260912-001312.tar.gz`; excludes Git, models and virtualenv
- [x] Native editor, settings, model manager, onboarding, microphone test, diagnostics and tray/launcher
- [x] Sequential worker, bounded queue, cancel/retry/crash recovery, job settings snapshots and process-group cleanup
- [x] Pinned model revisions, SHA verification, repair, interrupted download/resume, selection and removal
- [x] CPU/CUDA/Vulkan routing, OpenVINO backend, patched AMD NPU backend with CPU fallback and actual-device results
- [x] VAD edge padding/off switch, replacement dictionary, separate opt-in text/audio history
- [x] Transcript retention on optional settings/history/performance write failure; audio disk errors stop capture
- [x] Portal bridge and clipboard ownership transaction; live desktop acceptance is separate below
- [x] Desktop file, icon, AppStream metadata, application license and experimental Flatpak recipe

## Observed evidence

| Check | Result | Scope and evidence |
| --- | --- | --- |
| CPU baseline | 12 → 6 threads: 42.797 → 23.994 s; identical four transcripts | `baseline-cpu12.json`, `benchmark-cpu6.json`; four FLEURS clips, Thai CER 21/202 and English WER 3/40 |
| VAD smoke | Same aggregate Thai/English errors | `benchmark-qwen-vad.json`; development-load timings |
| NPU repeated jobs | 100 successful unique IDs, one worker, 25 identical repeats per source | `stress-npu-100.json`, `evidence/stress-npu-analysis.json`; sequential file ASR, not microphone/paste sessions |
| NPU SDK runtime | KDE 6.11 rebuild, device validation and ASR pass | `evidence/fastflowlm-sdk-build.json`, `HARDWARE.md`; experimental quality |
| Qwen mixed challenge | Four natural clips, 211/1108 character errors (19.04%), 5,982.5 MiB peak RSS | `benchmark-mixed-qwen.json`; builds paused, 93.70 s includes first model load |
| Vulkan mixed challenge | 282/1108 errors (25.45%), actual Radeon compute confirmed | `evidence/vulkan-asr.json`; concurrent-build timings are not a paired performance comparison |
| NPU mixed challenge | Four natural clips, 485/1108 character errors; one repetitive output | `benchmark-mixed-npu.json`; selected 96-second set, concurrent builds |
| Clean Flatpak CPU | Cached Thai ASR with network disabled and Librosa/Numba/SciPy absent | `evidence/flatpak-offline-cpu.json`; CPU Torch wheel package |
| Flatpak NPU/fallback | NPU with per-run device permission; default permissions produce one Qwen CPU result | `evidence/flatpak-npu-and-fallback.json`; lack-of-device fallback, not induced hardware crash |
| Native microphone | PCM16 mono 16 kHz capture; selected source removal and observer failure discard the WAV before ASR | `evidence/native-audio.json`; owned virtual sources only, host defaults unchanged |
| Packaged microphone | 10.688 s mono capture, peak 10%, no errors | `evidence/flatpak-audio.json`; owned virtual source/public audio, no physical mic |
| Mic removal | Capture stopped and emitted disconnect error | Same evidence; patched Qt 6.11.1 PulseAudio/DONT_MOVE |
| Download resume | Interrupted at 1,114,112 bytes; Range resumed with HTTP 206; hashes passed | `evidence/model-resume.json`; smaller test HTTP chunks, Xet disabled |
| Desktop portals | User-granted paste into owned Qt field exactly once; Meta+H actual activation; all original MIME payloads restored and newer copy preserved | `evidence/desktop-interactive-analysis.json`; Qt adds UTF-8 alias; cross-application focus remains separate |
| Long translation | Large chunks omitted text; short chunks retain source coverage, all 25 numeric markers and tail marker | `evidence/translation-long*.json`; synthetic coverage text, not a quality benchmark |
| Regression suite | 82 app tests + 6 legacy tests pass on the final native environment | Qt offscreen; rerun after consequential edits |
| UI | Four current native screenshots reviewed | `screenshots/`; not all themes/screen sizes |

The earlier failed PulseAudio removal test is retained in `microphone-disconnect-proof.json`. The later packaged test demonstrates the source fix; the unpatched native Qt wheel still has that limitation

## Current delivery scope

- [x] Native installer with dedicated environment, verified patched Qwen source, CPU Torch, import checks and user desktop launcher
- [x] Fresh native installation: four public Thai/English files, exactly one result per job, transcripts identical to the six-thread baseline (`evidence/native-clean-install-asr.json`)
- [x] Vulkan GPU and optimized CPU fallback through installed worker: 4.39 / 23.30 seconds for one 7.2-second Thai clip, same result, one job/result, server cleanup (`evidence/flatpak-vulkan-worker.json`)
- [x] User-assisted shortcut/paste, all original MIME payloads restored and newer copies preserved
- [x] README includes installation, daily use, updates, data locations, model limitations and legacy migration
- [x] .gitignore excludes personal config, keys, recordings, weights, runtime binaries, virtualenvs and build caches
- [x] Native microphone guard: owned virtual capture, source-removal discard, observer-failure discard, no ASR on either failed take (`evidence/native-audio.json`); current installed-app screenshots and independent reviews; owned observer exits when its test parent is killed (`evidence/native-guard-parent-exit.json`)
- [ ] GitHub SSH push and remote commit verification

SSH successfully authenticated as `Tatarus9450`; the origin remote uses `git@github.com:Tatarus9450/PhimThaiMaiPen.git`. Publishing follows the user's explicit instruction. Do not interpret local tests as a completed remote push

## Deferred work and explicit limits

Source-only Flatpak/Flathub work is paused by user request. Source PySide, Qt Multimedia, Rust tokenizers/safetensors, NumPy and CPU/Vulkan dispatch proofs are retained. Python PyTorch compilation stopped with cached objects (~1,421/2,507 native steps); no source-Torch wheel/import/ASR completion is claimed. The shipped native installer uses the official CPU Torch wheel

Broader tests remain future work: paired accuracy/latency across more speech, physical microphone unplug and suspend, 100 complete microphone/paste sessions, cross-application focus and clipboard history, persistent portal permission after restart, GNOME/X11, other distributions, CUDA and Intel NPU hardware. Qwen 1.7B remains a selectable unverified model. Experimental NPU quality is below Qwen on the small mixed-language challenge

No Flathub submission, Discover publication or hardware-wide compatibility certification is part of this delivery

## Rollback

Stop the new app and workers. Existing legacy environment/model cache remain available. Extract the backup into a separate directory and compare before restoring selected files. Never reset user changes wholesale. Record the Flatpak commit and preserve app data before testing package rollback; downloaded models live outside app updates
