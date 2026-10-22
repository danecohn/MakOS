# MakkOS asset provenance

No proprietary operating-system artwork, wallpapers, fonts, sounds, cursors or logos
were downloaded or extracted. Required upstream notices remain intact. Creation date:
2026-10-22. Original code, vectors, mathematical materials, cursor drawings and synthesized
sounds are GPL-3.0-only. The owner's rights, if any, in the generated AI art are dedicated
to CC0-1.0 for redistribution.

| File / family | Source | Licence | Author / attribution |
|---|---|---|---|
| All 55 app/folder/drive/file icons in `assets/makos/`, enumerated in `ASSET-VALIDATION.json` | Built-in imagegen, individual original prompts | CC0-1.0 dedication | Generated for MakkOS |
| `assets/makos/wallpaper-{aurora-blue,water-drop,nebula,hills,graphite,linen-grey}.png` | Built-in imagegen, original photographic compositions | CC0-1.0 dedication | Generated for MakkOS |
| `src/makos/icons/MakkOS/{16,32,48,64,128,256,512}x*/apps/*.png` | Resized from the original AI icons by `tools/ingest_makos_assets.py` | CC0-1.0 dedication | MakkOS |
| `src/makos/wallpapers/*.jpg` and previews | `tools/prepare_makos_wallpapers.py`, explicit resampling of the originals | CC0-1.0 dedication | MakkOS |
| `src/makos/icons/MakkOS/scalable/apps/makos-*.svg` | `tools/make_makos_vectors.py`, original geometric small-size fallbacks | GPL-3.0-only | MakkOS contributors |
| `assets/makos/{texture-*,button-*,traffic-light-*,dock-*,menubar-*,title-gradient-*,toolbar-*,scrollbar-*,badge-*,login-*}.png` | `tools/make_makos_materials.py`, original mathematical gradients, periodic patterns and drawings | GPL-3.0-only | MakkOS contributors |
| `assets/makos/makos-logo*.png` | Original geometric M mark, rasterized from the original SVG | GPL-3.0-only | MakkOS contributors |
| `src/makos/cursors/` and `icons/MakkOS-Cursors/` | Original cursor drawings, compiled with the distro's xcursorgen; no encoder executable is bundled | GPL-3.0-only | MakkOS contributors |
| `src/makos/sounds/{notification,login,trash,error}.wav` | Original additive/envelope synthesis in `tools/make_makos_materials.py` | GPL-3.0-only | MakkOS contributors |
| `src/makos/theme/glass.css` | Original CSS gradients, shadows and glass controls | GPL-3.0-only | MakkOS contributors |
| `src/makos/theme/decoration/contents/ui/*.qml` | Original QML using public decoration API conventions | GPL-3.0-only | MakkOS contributors |
| DejaVu Sans | Ubuntu `fonts-dejavu-core`; not bundled | Bitstream Vera / DejaVu font licences; `/usr/share/doc/fonts-dejavu-core/copyright` | DejaVu contributors / Bitstream |
| `src/makos/makos/{windows.py,shell/layer.py,shell/tray.py,backends/*.py}` | Existing Amerika OS plumbing, copied/adapted | GPL-3.0-only | Amerika LLC; MakkOS adaptations |
| `src/makos/shell-host.c`, packaging utilities | Existing dedicated shell host and package builder, adapted | GPL-3.0-only | Amerika LLC; MakkOS adaptations |
| `src/makos/compat/` Studio adapters | Existing Studio, Render, Engine, Sprite, Box sources, cosmetic copies | Existing GPL-3.0 / MIT notices under `compat/notices` | Amerika LLC and upstream contributors |
| `compat/box/beepbox*` | Existing bundled BeepBox engine, not newly downloaded | MIT; retained notices | John Nesky / BeepBox contributors |
| `compat/render/splash.png` | Original text composition with DejaVu Sans | GPL-3.0-only; font licence above | MakkOS contributors |

Full additional icon prompts are in `GENERATED-PROMPTS.json`; wallpaper prompts are in
`WALLPAPER-PROMPTS.json`. The first nine icon metaphors are: Files = glass folio with
ivory dividers; Terminal = smoked command console; Settings = nickel gears; Venture =
glass globe with silver orbit; Paper = ivory pages/blue ribbon; Digits = glass grid/abacus;
Notes = spiral pad; Calculator = silver calculator; Trash = frosted ribbed basket.
Each requests a single centered glossy 3D object, cool silver/blue, slight above-view,
soft reflections/contact shadow, transparent canvas, generous padding, no text or logos.

All 55 canonical icons are 1024x1024 RGBA and passed alpha, padding and centering checks.
Generated native icon dimensions were normalized explicitly; original native files remain
in the generation service's output location. The wallpaper service returned smaller native
images: shipped 3840x2160 JPEGs are resampled, not native-4K generation. Wallpaper validation
records both sizes. Periodic tiles have matching first/last rows and columns; their
seams, UI dimensions and compiled cursor headers are checked by the material validator.

Contact-sheet inspection checked consistent style and obvious unwanted motifs. Asset
testing is not a claim of feature completeness. Login/boot theme integration and sound
playback policy remain separate release gates even though some required artwork exists.

## Integration additions (2026-10-22)

The expanded GTK3/GTK4 stylesheets, Qt stylesheet, decoration metal/orb images,
Settings pane fallback vectors and Studio-suite fallback vectors in the handoff
are original MakkOS code/drawings under GPL-3.0-only. The small Settings/Studio
vectors are development artwork, not photographic AI icons. Exact generation is
in `tools/make_makos_vectors.py`; generated derivatives are not source inputs.

Paper, Digits and Slides launch Mak Office through the installed
`euro-office-euro-office --new:word|cell|slide` wrapper. Mak Office is an Amerika
LLC product packaged from Euro-Office Desktop Editors 9.3.5-2 for ARM64,
AGPL-3.0. Its upstream program and notices remain unmodified, including the
visible Euro-Office identity inside the editors. This is packaging and launcher
integration, not a built source fork or a completed MakkOS skin.
Corresponding-source links and the pin are recorded in the Mak Office package's
`/usr/share/doc/mak-office/SOURCE.md` and the packaging repository:
https://github.com/danecohn/amerikasocial/tree/main/amerika-os/src/os/makoffice
The wrapper sets its own CEF preload; the shell's layer-shell preload must never
be passed to it. No API keys or cloud account are needed for local documents.

`src/makos/venture/{venture.css,start.html}`: original MakkOS browser chrome and
local start page, MakkOS contributors, GPL-3.0-only. No third-party browser artwork
was extracted or traced. Existing native engine toolbar glyphs are rendered by the
installed browser under its retained upstream licence; no glyph assets are copied.

## Cherry Blossom identity (2026-10-22)

`src/makos/branding/cherry-blossom.svg` is original vector artwork created for
Cherry Blossom LLC and Makk OS. Five notched pink petals with a gold stamen centre;
no proprietary source artwork. GPL-3.0-only, as original project code/artwork.
`tools/make_makk_brand.py` renders the logo, boot watermark, native two-step
authentication icons and progress frames. DejaVu fonts retain their upstream licence.

The lock-screen QML is derived from the installed KDE Plasma 6.7.5 shell lock
screen, GPL-2.0-or-later, copyright Aleix Pol Gonzalez and the other KDE authors
listed in each source file. Its authentication and unlock flow are retained.
The background and brand header are downstream changes by Cherry Blossom LLC.
