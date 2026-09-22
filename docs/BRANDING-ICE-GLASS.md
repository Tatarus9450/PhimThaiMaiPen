# Ice glass and transparent mascot · 2026-09-22

The requested palette is light blue, white and black, keeping the native Liquid Glass interface with an iOS-inspired treatment. This updates the current source and native installation; it is not a new published Flatpak release.

## Logo provenance

- Reference: the project's original [GitHub banner](https://github.com/user-attachments/assets/29660b40-78aa-4a22-9727-46f81606c7ef)
- Tool: built-in ImageGen, using the banner as the mascot reference
- Final master: [1024 px transparent PNG](branding/penguin-microphone-transparent.png)
- Application icon: [512 px transparent PNG](../phimthai/assets/io.github.tatarus9450.PhimThaiMaiPen.png)
- The user explicitly authorized a separate background-removal tool after two ImageGen outputs contained opaque checkerboard pixels. The final asset uses Pillow/SciPy background extraction; it does not ship that fake checkerboard.

The cutout uses the mascot's closed black silhouette: remove bright, border-connected pixels, keep the single foreground component, soften the alpha boundary by 0.45 px, and extend the nearest interior colors into edge pixels to avoid a gray fringe. Opaque white eyes, belly and the enclosed microphone are preserved. The result is fitted within 860 px of a 1024 px canvas and downsampled with Lanczos. Alpha spans 0–255; the master has 654,494 fully transparent pixels, 380,947 opaque pixels and 13,135 antialiased edge pixels.

Visual inspection covers white, charcoal and light blue backdrops at large size and at 24, 32, 48 and 64 px. The same application asset supplies the sidebar, window and tray; the native desktop launcher installs it under the existing application ID.

### Generation prompt

```text
Use case: background-extraction and logo-brand refinement.
Asset type: production desktop application icon, square 1024x1024 transparent PNG with real alpha.
Input image: the official PhimThaiMaiPen GitHub banner, reference for the penguin mascot identity.
Primary request: Extract and beautifully refine only the penguin holding the microphone from this banner into a clean standalone application logo. Preserve its recognizable pose, big friendly eyes, black head and flippers, white oval belly, yellow beak and feet, and raised flipper holding the silver microphone on the viewer's right. Remove the keyboard, cable, flag, all text and all blue banner background.
Style: polished smooth illustrated app mascot, confident simple silhouette and clean antialiased edges, gentle dimensional highlights on black and silver, crisp at 32px, restrained and friendly. Preserve the original mascot's character; do not invent another animal.
Composition: whole penguin and entire microphone centered together, occupy about 84 percent of square canvas with comfortable transparent margin, no cropping.
Background: genuinely fully transparent alpha outside mascot. No colored tile, no white rectangle, no checkerboard pixels, no ground shadow, no halo or blue fringing. Keep belly and eyes white and opaque; only the outside and real gaps are transparent.
No letters, no badge, no borders, no watermark. Deliver the final cutout icon only.
```

### Follow-up prompt

```text
Edit the attached penguin application logo. Keep the mascot and microphone exactly as drawn, preserve all its colors and details. Remove every gray checkerboard pixel from the background and the gaps around and between its flippers. Output a PNG with actual alpha transparency. This is a background removal task, not a picture of transparency: do not paint a checkerboard, white, gray or any opaque background. The entire external background must have alpha=0 and the mascot including its white belly and eyes must remain opaque. Crisp clean antialiased silhouette edges without gray halos. Keep the entire mascot and microphone with a small transparent margin in the square image. Use the actual transparent-background output capability.
```

## Interface

The existing Qt layout and native controls remain. Pale blue carries primary actions and selection, near-black text carries content, and translucent white panels sample and slightly magnify the app's own cached backdrop. Soft light ribbons, fine reflective rims and offset shadows give the panels depth. This material is composed inside the app; it does not capture or blur other desktop windows.

Text remains opaque for readability. Reduced transparency uses uniform solid surfaces. Rendering has no continuous animation timer or GPU effect. The palette stays consistent under both light and dark desktop settings.

The appearance regression suite passes. A separate scan over both the brightest and darkest interior pixels, at 820×600 and 1040×760 in glass and solid modes, measured minimum contrast of 12.24:1 for body text and 4.91:1 for secondary text. The offscreen 32-case layout pass found no geometry issues. Final native screenshots and installed-worker evidence are recorded separately in `evidence/ice-glass-native.json`.
