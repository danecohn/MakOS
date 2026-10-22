# MakOS asset provenance

No proprietary operating-system artwork, wallpapers, fonts, logos, sounds or cursors
were downloaded or extracted. Required upstream notices remain in their packages.
MakOS code and original vector/UI art: GPL-3.0-only. Owner's rights, if any, in the
AI-generated art are dedicated to CC0-1.0 for redistribution. AI generation is not a
trademark-clearance guarantee. Creation date: 2026-10-22.

| File / family | Source | Licence | Author / attribution |
|---|---|---|---|
| `assets/makos/wallpaper-aurora-blue.png` | Built-in imagegen, original aurora/lake prompt | CC0-1.0 dedication | Generated for MakOS |
| `assets/makos/{files,terminal,settings,browser,file-document,file-spreadsheet,notes,calculator,trash-empty}.png` | Built-in imagegen, individual original object prompts | CC0-1.0 dedication | Generated for MakOS |
| `src/makos/icons/MakOS/{16,32,48,64,128,256,512}x*/apps/*.png` | Derived by `tools/ingest_makos_assets.py` from the above | CC0-1.0 dedication | MakOS |
| `src/makos/icons/MakOS/scalable/apps/makos-*.svg` | `tools/make_makos_vectors.py`, original geometric drawings | GPL-3.0-only | MakOS contributors |
| `src/makos/theme/glass.css` | Original CSS gradients, shadows and glass controls | GPL-3.0-only | MakOS contributors |
| `src/makos/theme/decoration/contents/ui/*.qml` | Original QML; public decoration API conventions | GPL-3.0-only | MakOS contributors |
| DejaVu Sans | Ubuntu `fonts-dejavu-core`; not bundled | Bitstream Vera / DejaVu font licences, see `/usr/share/doc/fonts-dejavu-core/copyright` | DejaVu contributors / Bitstream |
| `src/makos/makos/{windows.py,shell/layer.py,shell/tray.py,backends/*.py}` | Existing Amerika OS repository plumbing, copied/adapted | GPL-3.0-only | Amerika LLC; MakOS adaptations |
| `src/makos/shell-host.c` | Existing dedicated Amerika shell host, adapted module name | GPL-3.0-only | Amerika LLC; MakOS adaptations |
| `src/makos/compat/` Studio adapters | Existing Studio, Render, Engine, Sprite, Box source, cosmetic copies | Respective existing GPL-3.0 / MIT notices retained under `compat/notices` | Amerika LLC and upstream contributors |
| `compat/box/beepbox*` | Existing bundled BeepBox engine; not newly downloaded | MIT; retained engine notices | John Nesky / BeepBox contributors |
| `compat/render/splash.png` | Original deterministic text composition, DejaVu rendered font | GPL-3.0-only; font licence above | MakOS contributors |

Image prompts: each app icon is a single isolated glossy 3D object, soft reflection,
cool silver/blue, above-view, gentle shadow, transparent canvas. Specific metaphors:
Files = glass folio with ivory dividers and silver clasp; Terminal = smoked command
console; Settings = interlocking nickel gears; Venture = glass globe with silver orbit;
Paper = ivory pages with blue ribbon; Digits = glass grid/abacus; Notes = spiral pad;
Calculator = silver calculator; Trash = frosted ribbed basket. Exclusions: existing
OS icons, logos, fruit shapes, smiley faces and proprietary fonts.

The wallpaper prompt requests an original cyan/cobalt aurora over a calm dark lake,
small stars, mist and low mountains. Built-in tool output was 1672x941, not native
3840x2160; no native-4K claim is made. Generated icons were 1254x1254 and are normalized
to 1024x1024 during explicit ingestion. Validation records original sizes and alpha.

Only the listed AI images exist. The other requested high-detail AI icon families,
wallpapers, texture tiles, cursor artwork and full sound set remain release gates.
The original small vector drawings are development assets, not passed off as the
requested photographic AI artwork. CSS replaces image-based UI gradients in this build.
