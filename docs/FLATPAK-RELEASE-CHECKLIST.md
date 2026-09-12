# GitHub Flatpak beta delivery — 2026-09-12

Delivered: [PhimThaiMaiPen 2.0.0-beta.1](https://github.com/Tatarus9450/PhimThaiMaiPen/releases/tag/v2.0.0-beta.1), a public GitHub prerelease with eight downloadable assets. The x86_64 Flatpak defaults to **Qwen3-ASR 0.6B / Smart Mix**, with automatic language and device selection. Existing user selections are preserved

## Completed acceptance

- [x] Publish source and tag at commit [`3ec06c4c1d0fd20d92e99d0b67c9c1f796642d49`](https://github.com/Tatarus9450/PhimThaiMaiPen/commit/3ec06c4c1d0fd20d92e99d0b67c9c1f796642d49); package version `2.0.0b1`, Flatpak branch `beta`
- [x] Build from a clean GitHub runner using pinned CPU PyTorch and PySide 6.11.1 wheels, source-patched Qt Multimedia and Qwen, and the OpenVINO runtime. Experimental AMD NPU/Vulkan runtime artifacts and model weights are excluded
- [x] Include corresponding dependency notices: **152 sources and 4,174 collected notice files**
- [x] Pass **112 local application regression tests** and **32 isolated UI cases**, keeping the running native application and its text untouched
- [x] Validate desktop metadata, packaged runtime imports and factory defaults. Verify all **31 application source/assets files** against the checkout and **129 dependency requirements**, with no failures
- [x] Run actual Qwen CPU transcription of two hash-pinned public audio clips with networking disabled, using the packaged `/app` code and Platform runtime
- [x] Export the bundle and successfully import it into a separate repository without installing over the running native application
- [x] Complete [GitHub Actions run `34675954504`](https://github.com/Tatarus9450/PhimThaiMaiPen/actions/runs/34675954504/job/103505737063), publish the prerelease, and confirm all eight assets are publicly available
- [x] Download all eight published assets and verify each SHA-256 against the GitHub API digest; also verify the Flatpak against `SHA256SUMS`

## Artifact identity

| Field | Verified value |
| --- | --- |
| Bundle | [`PhimThaiMaiPen-2.0.0-beta.1-x86_64.flatpak`](https://github.com/Tatarus9450/PhimThaiMaiPen/releases/download/v2.0.0-beta.1/PhimThaiMaiPen-2.0.0-beta.1-x86_64.flatpak) |
| Size | **406,093,240 bytes** — approximately 387.3 MiB |
| SHA-256 | `d4368f470ace7dd2b042e749d338213971d525dbaa3983f3c2c91a74db7a1da5` |
| Checksum file | [`SHA256SUMS`](https://github.com/Tatarus9450/PhimThaiMaiPen/releases/download/v2.0.0-beta.1/SHA256SUMS), matching the GitHub asset digest |
| Runtime | KDE Platform 6.11, Qt / PySide 6.11.1, CPU PyTorch `2.11.0+cpu` |
| Publication | 2026-09-12 06:00:48 UTC; public prerelease, not a draft |

The [GitHub delivery evidence](evidence/flatpak-beta-github.json) records the release and download verification. Public assets also include the resolved manifest, pinned wheel URLs/checksums, dependency constraints, build provenance and runtime smoke/ASR reports

## ASR evidence and beta limits

The [published offline ASR report](https://github.com/Tatarus9450/PhimThaiMaiPen/releases/download/v2.0.0-beta.1/PhimThaiMaiPen-2.0.0-beta.1-x86_64-asr.json) passed on two Google FLEURS clips: Thai CER **2/75 (2.67%)** and English WER **1/19 (5.26%)**. It used two CPU threads, completed in 18.018 seconds and recorded peak process RSS of 5,841 MiB. The Qwen model revision and all model files passed integrity checks

These are two known public clips used to check that the packaged app works; they do not establish general accuracy or speed on other computers. The CI check does not record a microphone or operate desktop shortcuts, sound output, clipboard or another application's window. Local isolated desktop checks remain separate evidence, and do not certify every Linux distribution, physical microphone or paste destination

This is a **direct GitHub Flatpak download**, not a Flathub submission or searchable Flathub listing. Models and the KDE runtime download separately. The small left-side popup requires XWayland on Wayland desktops. There is no application update remote; install a newer bundle to update

Rollback: keep the working native application available, use isolated data/config for verification, and preserve model/user data when installing an earlier bundle. See [distribution instructions](DISTRIBUTION.md) for installation, updates and rollback
