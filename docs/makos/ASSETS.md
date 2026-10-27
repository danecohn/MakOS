# VigilOS asset provenance

No proprietary operating-system artwork, wallpapers, fonts, sounds, cursors or logos
were downloaded or extracted. Required upstream notices remain intact. Creation date:
2026-10-22. Original code, vectors, mathematical materials, cursor drawings and synthesized
sounds are GPL-3.0-only. The owner's rights, if any, in the generated AI art are dedicated
to CC0-1.0 for redistribution.

| File / family | Source | Licence | Author / attribution |
|---|---|---|---|
| App, folder and drive icons in `assets/makos/` | VigilTech macOS kit (rose set), folders at 1024 px, app icons resampled from 512 px | GPL-3.0 | VigilTech |
| `assets/makos/file-*.png` | Earlier generated set, hue-shifted to rose; pending replacement | CC0-1.0 dedication | Generated for MakkOS |
| `assets/makos/wallpaper-{nave,ridge,starfall,rose-window}-{night,dawn}.jpg` | VigilTech macOS kit, 5120x2880 resampled to 3840x2160 | GPL-3.0 | VigilTech |
| `src/makos/icons/MakkOS/{16,32,48,64,128,256,512}x*/apps/*.png` | Resized from the original AI icons by `tools/ingest_makos_assets.py` | CC0-1.0 dedication | MakkOS |
| `src/makos/wallpapers/*.jpg` and previews | `tools/prepare_makos_wallpapers.py`, explicit resampling of the originals | CC0-1.0 dedication | MakkOS |
| `src/makos/icons/MakkOS/scalable/apps/makos-*.svg` | `tools/make_makos_vectors.py`, original geometric small-size fallbacks | GPL-3.0-only | MakkOS contributors |
| `assets/makos/{texture-*,button-*,traffic-light-*,dock-*,menubar-*,title-gradient-*,toolbar-*,scrollbar-*,badge-*,login-*}.png` | `tools/make_makos_materials.py`, original mathematical gradients, periodic patterns and drawings | GPL-3.0-only | MakkOS contributors |
| `assets/makos/makos-logo*.png` | Original geometric M mark, rasterized from the original SVG | GPL-3.0-only | MakkOS contributors |
| `src/makos/cursors/` and `icons/MakkOS-Cursors/` | Original cursor drawings, compiled with the distro's xcursorgen; no encoder executable is bundled | GPL-3.0-only | MakkOS contributors |
| `src/makos/sounds/{notification,login,trash,error}.wav` | Copied by `tools/make_makos_materials.py` from `brand/vigiltech/sounds` | GPL-3.0 | VigilTech |
| `src/makos/theme/glass.css` | VigilTech-token CSS | GPL-3.0-only | MakkOS contributors |
| `src/makos/theme/decoration/contents/ui/*.qml` | Original QML using public decoration API conventions | GPL-3.0-only | MakkOS contributors |
| DejaVu Sans | Ubuntu `fonts-dejavu-core`; not bundled | Bitstream Vera / DejaVu font licences; `/usr/share/doc/fonts-dejavu-core/copyright` | DejaVu contributors / Bitstream |
| `src/makos/makos/{windows.py,shell/layer.py,shell/tray.py,backends/*.py}` | Existing Amerika OS plumbing, copied/adapted | GPL-3.0-only | VigilTech; MakkOS adaptations |
| `src/makos/shell-host.c`, packaging utilities | Existing dedicated shell host and package builder, adapted | GPL-3.0-only | VigilTech; MakkOS adaptations |
| `src/makos/compat/` Studio adapters | Existing Studio, Render, Engine, Sprite, Box sources, cosmetic copies | Existing GPL-3.0 / MIT notices under `compat/notices` | VigilTech and upstream contributors |
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

Paper, Digits and Slides launch Vigil Office through the installed
`euro-office-euro-office --new:word|cell|slide` wrapper. Vigil Office is an Amerika
LLC product packaged from Euro-Office Desktop Editors 9.3.5-2 for ARM64,
AGPL-3.0. Its upstream program and notices remain unmodified, including the
visible Euro-Office identity inside the editors. This is packaging and launcher
integration, not a built source fork or a completed MakkOS skin.
Corresponding-source links and the pin are recorded in the Vigil Office package's
`/usr/share/doc/mak-office/SOURCE.md` and the packaging repository:
https://github.com/danecohn/amerikasocial/tree/main/amerika-os/src/os/makoffice
The wrapper sets its own CEF preload; the shell's layer-shell preload must never
be passed to it. No API keys or cloud account are needed for local documents.

`src/makos/venture/{venture.css,start.html}`: original MakkOS browser chrome and
local start page, MakkOS contributors, GPL-3.0-only. No third-party browser artwork
was extracted or traced. Existing native engine toolbar glyphs are rendered by the
installed browser under its retained upstream licence; no glyph assets are copied.

## VigilTech identity (2026-10-27)

The Cherry Blossom emblem is retired. VigilOS uses the VigilTech product icon (`brand/vigiltech/icons/os-*.png`,
`src/makos/branding/vigilos.svg`), the Vigil Sans typeface (SIL OFL 1.1), the VigilTech design tokens and sounds
(`brand/vigiltech/`), and artwork from the VigilTech macOS kit: wallpapers (`assets/makos/wallpaper-*.jpg`, Nave, Ridge,
Starfall and Rose Window in Night and Dawn), folder icons and app icons (`assets/makos/folder*.png` and the app and
drive icons). All GPL-3.0 / OFL-1.1 as stated in `brand/vigiltech/LICENSE`. The `file-*` type icons in
`assets/makos/` are the earlier generated set, hue-shifted to the VigilTech rose; a native VigilTech file-type set is pending.
`tools/make_makk_brand.py` renders the boot watermark, native two-step authentication icons and progress frames.

The lock-screen QML is derived from the installed KDE Plasma 6.7.5 shell lock
screen, GPL-2.0-or-later, copyright Aleix Pol Gonzalez and the other KDE authors
listed in each source file. Its authentication and unlock flow are retained.
The background and brand header are downstream changes by VigilTech.

## Encrypted-root boot guard

`makk-boot-check` validates active root dependencies against `/etc/crypttab` and
each initramfs. It checks mapping name/UUID, explicit initramfs inclusion,
cryptsetup, native passphrase prompt, cryptroot scripts, and LVM where required.
It never opens key files or changes encryption. The initramfs build hook validates
the staged tree after cryptroot/lvm2 hooks, before update-initramfs publishes it.
Brand activation validates images before/after rebuilding; revert refuses stale
snapshots without current encrypted-root support. Packages never activate themes.
A passing guard is a structural check, not a real boot/unlock acceptance test.
