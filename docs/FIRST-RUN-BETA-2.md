# First launch and experimental accelerators

Task: a new user opens the app, sees the recommended Qwen3-ASR 0.6B download start automatically, and receives desktop requests for Meta+H, Meta+Shift+H and paste. Keep model deletion and support importing compatible external model folders. Mark GPU/NPU Beta in red with the requested warning

INTENT: code and README currently require manual model download and permission buttons; the user explicitly requests automatic first-launch setup, later model management and red GPU/NPU Beta warnings. The new user request supersedes the manual setup instructions

AUTH: user said "อัปขึ้นGithub และทำให้แอปยึดโมเดลนี้เป็นค่าเริ่มต้น และทำเป็นFlat packเลย"; this follow-up updates that delivered app with a new beta, without replacing the immutable beta 1 assets

Scope: application startup/settings/model management, compatible local model import, desktop permission sequencing, CPU automatic policy, warning presentation, focused tests, documentation and beta release metadata

- [x] Persist download/setup state separately from transcript onboarding; preserve existing user settings
- [x] Start recommended download after first window opens; report status, cancellation, resume and failure on the main page
- [x] Request shortcuts and paste sequentially, obey OS consent, show actual readiness and avoid repeat prompts after denial
- [x] Import supported local model data into private managed storage with atomic publication and distinct local provenance; retain deletion and switching
- [x] Keep Auto on CPU; label GPU/NPU Beta with a red development warning
- [x] Test clean first launch, cancellation/relaunch, deletion, import integrity, permission denial and UI layouts without touching the running native app
- [ ] Publish beta 2 source and Flatpak after clean build/runtime checks; verify public downloads

Evidence: app.py startup only restores opted-in desktop sessions; download is a manual QProcess action. models.py accepts static CATALOG IDs; worker validates those IDs in its own process. Auto may select GPU from benchmark history. portals.py emits completion after both successful and denied requests, so readiness must follow enabled events, not completion

Verification limits: automated tests isolate OS permissions, clipboard and microphone. A desktop may require the user's first consent and may not support the portal. Models must finish downloading before transcription can work. External model imports support the existing Qwen3-ASR and Whisper OpenVINO/GGML formats, not arbitrary model code

Local verification: 142 application tests passed; 32 isolated UI cases, zero geometry issues. Independent review confirmed interrupted permission setup, cold hotkey restoration and failed settings writes. No live microphone, clipboard, desktop grants or native restart during these checks

TWINS: searched automatic device selection across devices.py, openvino_backend.py and vulkan_backend.py; all three now keep Auto on CPU. Partial portal shortcut updates preserve the other action instead of clearing its binding
