# GitHub Flatpak beta delivery — 2026-09-12

Authorized outcome: preserve Qwen3-ASR 0.6B / Smart Mix as the default, publish updated source to GitHub, and provide an installable x86_64 Flatpak. Existing native dictation is working and must remain available while packaging is tested

## Plan and acceptance

1. Verify running configuration and factory defaults; version the beta consistently
2. Package CPU inference, UI/audio, model manager and corresponding license notices; exclude experimental AMD/Vulkan runtime artifacts
3. Verify package requirements, actual runtime imports, first-run defaults, isolated UI and offline ASR using public test audio
4. Export/install a bundle without replacing the running native application; verify metadata and checksum
5. Publish source/tag and a GitHub prerelease with bundle, checksums and build provenance; confirm downloadable assets

Rollback: keep the current native process and its text untouched. Test Flatpak in an isolated data/config environment. Source changes are versioned; keep model data when reinstalling any earlier bundle. A direct GitHub bundle is not Flathub approval

## Evidence

- Native configuration inspected: Qwen 0.6B, Smart Mix, automatic language/device selection
- Factory settings already match; release build asserts these values and does not overwrite user selections
- First beta export built successfully with source PySide; public recipe is being rechecked with wheel PySide to match clean CI builds
- Final verification, artifact digest and GitHub release URL will be recorded after successful checks
