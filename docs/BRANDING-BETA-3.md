# Penguin microphone identity · beta 3

The user requested a generated, lettering-free penguin holding a microphone, based on the project's original GitHub mascot, and a less monotonous Liquid Glass interface.

## Source and generation

- Original [GitHub banner](https://github.com/user-attachments/assets/29660b40-78aa-4a22-9727-46f81606c7ef), used by [README commit 9607534](https://github.com/Tatarus9450/PhimThaiMaiPen/commit/9607534195479265d352de9ebe4d64a1cde97050) on 2026-04-18
- Tool: built-in ImageGen, 2026-09-12
- Selected master: [penguin-microphone-master.png](branding/penguin-microphone-master.png)
- App asset: [512 px PNG](../phimthai/assets/io.github.tatarus9450.PhimThaiMaiPen.png), conventionally downsampled from the generated master
- The first generated variant had a baked checkerboard, not an alpha channel. A second ImageGen edit replaced it with cobalt, so the shipped asset is intentionally opaque and contains no fake transparency

### Initial prompt

```text
Use case: logo-brand.
Asset type: final Linux desktop app icon for PhimThaiMaiPen.
Input image 1 is the project's original GitHub banner, a reference for mascot identity only. Redesign ONLY its friendly black-and-white penguin holding a handheld microphone into a polished, distinctive icon.
Subject: one cheerful upright Tux-like penguin, glossy charcoal-black head and flippers, warm white face/oval belly, big friendly eyes, golden yellow beak and feet; one flipper holds a silver handheld microphone close to its face. Preserve the recognizable penguin-and-mic silhouette from the reference.
Style: carefully crafted modern desktop mascot icon, gently sculpted enamel-like forms, clean confident contours, subtle controlled highlights, crisp readable silhouette even at 32 pixels. Charming and expressive, refined rather than toy clutter.
Composition: square 1024x1024, full penguin including both feet and microphone, centered, filling roughly 84% of canvas with safe padding. True transparent alpha background, freestanding icon, no square tile or scenery.
Text: NONE. Absolutely no letters, words, numbers, initials or watermark.
Avoid: banner, keyboard, flag, cables, extra objects, sparkles, background gradients, text of any kind, excessive tiny details.
```

### Final edit prompt

```text
Edit this generated app icon. Keep the exact friendly black-and-white penguin holding its silver microphone, golden beak and feet, expressive eyes, and polished illustration. NO TEXT anywhere.
Replace ALL gray checkerboard with a perfectly clean flat deep cobalt-blue background (#2448a0); checkerboard is unwanted and must disappear completely. This is a final full-bleed square app icon, not a mockup. Scale the penguin down slightly to leave a consistent 9% blue safe margin above and below both feet and head, and enough margin around microphone and flipper. Output a square high-resolution PNG with a solid cobalt background, no transparency or fake transparency. No external shadow, no frame, no tiles, no extra objects, no letters.
```

## Interface contract

This is a refinement of the existing native Qt Liquid Glass interface, preserving its layout and recording behavior. Neutral charcoal glass removes the previous all-teal treatment. Cobalt marks the main action and selection; warm amber identifies mode and setup; the editable transcript uses an ivory surface with dark text. Red is reserved for experimental accelerator warnings. Text and borders must remain legible under both desktop color schemes and reduced transparency.

The penguin appears in the sidebar, window, tray and installed desktop icon. The logo artwork contains no letters. The native installer migrates only the app's own former scalable icon after the new PNG is copied successfully. Flatpak installs the 512 px raster under the same application ID.

## Validation

Local verification: the complete 144-test application suite passed before the final record-availability test was added; the 37-test focused pass includes that new test, application flow regressions and all six legacy ASR tests. Final render batch: 32 theme/size/page cases plus two first-download/ready states, zero geometry issues. An independent reviewer verified text contrast (minimum measured 5.03:1 for transcript placeholder), icon identity, and the corrected unavailable-record action. The same source passed GitHub application checks on Python 3.11 and 3.13. Native beta 3 was installed without replacing dependencies or restarting the current window; application/asset hashes and the desktop icon match the source. The [beta 3 Flatpak](https://github.com/Tatarus9450/PhimThaiMaiPen/releases/tag/v2.0.0-beta.3) passed runtime imports, bundle import, source/desktop icon hash checks and offline CPU transcription of two public FLEURS clips. The first-launch settings in the packaged runtime match the requested automatic download, Smart Mix and immediate-paste defaults. See [local evidence](evidence/branding-beta3-local.json). Isolated UI checks use simulated services and never record audio, request desktop permissions or change the running app's clipboard.


Public download verification: all eight release assets were downloaded atomically and their sizes and SHA-256 digests match GitHub metadata. The actual 406,518,232-byte bundle also passed the published checksum manifest. [Release evidence](evidence/github-beta3-release.json) records the exact source tag, runtime icon digest and validation limits. The downloaded bundle was not installed alongside the running native application.
