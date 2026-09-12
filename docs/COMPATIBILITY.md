# Compatibility evidence

Recorded 2026-09-12. This is a test ledger, not a promise of support on every Linux distribution. An installed tool or detected device does not prove application operation.

## Observed development environment

- Fedora 44 KDE, x86_64; AMD Ryzen AI 5 340 CPU
- Kernel `7.1.13-200.fc44.x86_64`
- `XDG_CURRENT_DESKTOP=KDE`, `XDG_SESSION_TYPE=wayland`
- `plasmashell --version`: `plasmashell 6.7.4`
- `flatpak --version`: `Flatpak 1.18.2`
- AMD NPU detection/XRT enumeration passed; stock FLM 1.0.5 truncated Thai. Native and KDE Platform 6.11 sandbox proofs with the same two orchestration changes completed all four clips with identical text, reducing combined Thai CER from 50% to 19.31%; wider quality validation remains pending — see [hardware evidence](HARDWARE.md)

Desktop environment variables and version commands establish the host identity only. V2 microphone capture, portal shortcuts, clipboard preservation, target-app paste and Flatpak execution each need observed tests. Previous legacy application results do not automatically qualify V2.

## Release validation matrix

| Platform | Inventory | V2 native end-to-end | V2 Flatpak end-to-end | Accelerator ASR |
| --- | --- | --- | --- | --- |
| Fedora 44 KDE / Wayland / AMD x86_64 | Observed above | Pending | App end-to-end tracked separately; packaged Vulkan GPU/CPU fallback worker and isolated SDK-built NPU runtime passed | FLM NPU execution passed natively and in KDE Platform 6.11; patched quality experimental; isolated Vulkan GPU passed eight clips, quality experimental |
| Fedora KDE / X11 | Pending | Pending | Pending | Pending |
| Fedora GNOME / Wayland | Pending | Pending | Pending | Pending |
| Ubuntu GNOME / Wayland and X11 | Pending | Pending | Pending | Pending |
| Kubuntu KDE / Wayland and X11 | Pending | Pending | Pending | Pending |
| Debian KDE/GNOME | Pending | Pending | Pending | Pending |
| Linux Mint | Pending | Pending | Pending | Pending |
| Arch Linux | Pending | Pending | Pending | Pending |
| openSUSE KDE/GNOME | Pending | Pending | Pending | Pending |
| Intel NPU / Core Ultra host | Pending | Pending | Pending | OpenVINO documented; execution pending |
| ARM64 host | Pending | Pending | Pending | Pending |

The isolated Vulkan probe additionally detects the Radeon 840M as an integrated GPU in KDE Platform 6.11 with `--device=dri`; whisper.cpp v1.9.4 CLI/server and shared-library closure pass in that runtime, with generic x86_64 CPU flags; a subsequent isolated Vulkan ASR proof completed eight full FLEURS/TVSpeech clips with successful Vulkan0 allocation, renderD128 access and increasing AMD DRM compute counters. CPU-only llvmpipe and duplicated raw ICD entries are recorded separately. This passes the isolated GPU execution gate on this exact host, with experimental quality; hardware enumeration alone or this runtime proof does not pass full application end-to-end gates.


The replacement Vulkan runtime uses CPU modules selected at runtime: generic x64 and Haswell AVX2, with an OSXSAVE/XGETBV guard compiled at baseline ISA. On this exact host, CPU-only no-DRI and real Vulkan GPU each completed the same 7.2-second Thai clip twice with identical text; CPU selected Haswell and took 56.091/57.718 s, GPU took 4.839/4.263 s. All nine ELF dependencies resolved in KDE Platform 6.11. [Replacement runtime evidence](evidence/vulkan-cpu-dispatch.json) includes module maps, DRM compute deltas, source patch and cleanup. Its generic-only model-free probe ran on the same modern CPU; no older CPU or other distribution has been verified. The original scalar timeout remains in [failure evidence](evidence/vulkan-cpu-scalar.json). This replaces the runtime smoke gate only; neither complete-app fallback nor the full eight-clip accuracy suite has been rerun with this replacement runtime.


The installed Flatpak worker now passes GPU and GPU-unavailable CPU fallback at commit `efb38fd8d00b460e55028473efbec18ed8839f738f9585d0ca530c7c2afecc40` on this same host. [Installed worker evidence](evidence/flatpak-vulkan-worker.json) records one 7.2-second Thai clip per final case, six threads, network isolation, exactly one result per ID and graceful EOF server reaping. Vulkan worker elapsed time was 4.387 s; requesting GPU with DRI removed fell back to the same model on CPU in 23.300 s. Text matched across devices (CER4/75). This passes the packaged worker/fallback gate, while GUI, microphone/paste, forced accelerator failure, idle cleanup and other platform rows require their own evidence.

The isolated NPU sandbox test used `--device=all` for that invocation, recorded device file access and runtime maps, and stopped its server afterward. It did not add a persistent override or test a released application package. Least-privilege packaging and the full application flow remain separate gates.

The matrix groups intended tests; each passing result must name an exact distribution version, desktop, session type, architecture, app revision, model revision and runtime. Results from one combination must not mark another as passed.

## Native KDE shortcut registration

[KDE registration evidence](evidence/kde-shortcut.json), 2026-09-12: the previous portal `record` component was inactive while it still reserved Meta+H. Native desktop actions `io.github.tatarus9450.PhimThaiMaiPen.desktop` / `Record` and `CycleMode` now own Meta+H and Meta+Shift+H and report active after the registration process exits. They use the installed native launcher with `--toggle` and `--cycle-mode`. The owned legacy record/profile actions were removed; unrelated shortcut configuration sections retained the same SHA-256. A private backup records every affected desktop and binding. A full desktop logout/login was not performed.

[Installed shortcut route proof](evidence/kde-shortcut-route.json) passed with dev2 and Qt 6.11.2: invoking the actual registered KDE service actions launched the unchanged native command, reached the application's real single-instance IPC, changed recording false → true → false, and cycled smart → raw → th_to_eng → smart. Exactly one synthetic WAV reached the intercepted ASR submission boundary; no speech worker launched. The proof substituted only Recorder, ASR submission and settings saving, used an isolated config and offscreen window, and left the real settings/desktop/shortcut configuration unchanged. Its child and temporary WAV were removed. This verifies action dispatch and application state transitions; it does not prove a physical keypress, physical microphone capture, recognition accuracy or paste delivery.

[User shortcut observation](evidence/kde-user-shortcut.json) subsequently recorded four user-generated Meta+H launches, each carrying `--toggle` to the installed dev2 app and its correct instance lock. The user confirmed that the physical shortcut and microphone work, then clarified that the remaining symptoms concerned automatic paste and popup/sound feedback. The temporary launcher-only diagnostic was removed and the original launcher hash restored; no binding changed during this diagnosis. No agent injected keys or accessed recorded audio or transcript content.

## Sequential worker stress evidence

[100-job audit](evidence/stress-npu-analysis.json): 100 unique successful delivered IDs, one observed worker PID, 25 identical repetitions per source across four FLEURS WAVs, no reported failures and final temporary-directory removal. All responses reported FastFlowLM/NPU; the separate hardware proof records actual NPU file access. The runner submits one request at a time and does not exercise a pending backlog. It does not prove microphone capture, shortcuts, clipboard preservation, exactly-once paste, active cancellation, crash recovery or CPU fallback. Its latency excludes parts of application startup and all recording/paste. The stress result alone cannot mark any end-to-end platform row passed.

Four recorded TVSpeech Thai–English clips now have pinned references, hashes and attribution in [the mixed subset manifest](evidence/tvspeech-mixed-subset.json). Availability of those inputs does not by itself pass the mixed-language accuracy gate; each backend needs observed results. The subset is small and deliberately selected, not representative of all conversational speech.

## Required evidence for a passing row

1. Install on a clean system, launch without a terminal, select and download a model, restart with settings preserved, then uninstall and update successfully.
2. Capture from a chosen microphone; stop, cancel and retry; test disconnection and silence. Transcribe Thai, English and mixed-language recordings with saved expected text and actual output.
3. Use a global shortcut while another app has focus; verify permission handling and a visible fallback when the desktop cannot provide it.
4. Edit text and paste into representative target applications. Check clipboard preservation, history behavior, focus changes, cancellation and absence of duplicate delivery.
5. Test the installed Flatpak separately from the native app: microphone, portals, model storage/downloads and any accelerator access. Record permissions actually needed.
6. Record cold/warm latency, peak memory, Thai CER, English WER and mixed-language results. Run repeated-session and worker-crash checks. Only paired measurements can establish the performance target.

## Distribution status

Flatpak is installed on the observed host. That alone establishes neither a working application package nor a Discover listing. Flathub source/build, license, metadata and review gates must pass, and the user's Discover must have the Flathub remote enabled. No public Flathub acceptance or Discover availability is claimed by this document.
