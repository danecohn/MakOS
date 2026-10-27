# VigilTech brand guide

**VigilTech** makes free, open-source software. Founded by **Demetria Althea Cohn** (online: **Demie Althea Cohn**). VigilTech is the home of what was AltStack, Artemis Softworks and Cohnsoft. Site: **vigiltech.org**.

> Calm software, made in the open.

## Principles

- **Free software.** Everything we make is open source under the GNU GPL v3: code, icons, wallpapers, sounds.
- **Respect for people.** No ads, no tracking, no dark patterns.
- **Honest.** Software says what it does.
- **Quiet by default.** No streak guilt, no notification pressure.
- **Made with care.** Good typography, good icons, small details.

## Identity

The mark is a **lamp**: a flame over a bowl, with a small cross cut into the bowl and a four-point star beside it, on a **pink** tile. The flame is a vesica, the lens made where two pointed arches overlap; the bowl is an upside-down lancet arch. "Vigil" means keeping watch. The wordmark is **vigiltech**, lowercase, in Vigil Sans Bold: "vigil" in ink (or bone white on dark) and "tech" in VigilTech Pink.

| Asset | Use |
|---|---|
| **App icon** `logos/app-icon/` | Dock, launchers, stores. Has the soft margin and shadow of a desktop icon. |
| **Mark** `logos/mark/` | Favicons, avatars, small UI. Fills its canvas. Drawn natively at 16, 32, 48, 64, 128, 256, 512 and 1024 px, so small sizes stay crisp. |
| **Glyph** `logos/glyph/` | The lamp and star alone, in pink, white or black, for any background or one-colour print. |
| **Lockup** `logos/lockup/` | Mark + wordmark, horizontal or stacked; light and dark. The default signature. |
| **Pixel mark** `logos/pixel/` | The 64-pixel version, made in AltStack Sprite, for retro contexts and games. |
| **Social card, wallpapers** | `logos/social/`; `logos/wallpaper/` (night is the default, dawn is the light alternative). |

Every raster logo has an editable Sprite document in `source/` (`.asprite.json`) and a vector twin (`.svg`) where it matters.

**Clear space:** keep at least the height of the star free on all sides; one tile-height around the lockup is better.
**Minimum size:** mark 16 px; lockup 96 px wide; wordmark alone 64 px wide.
**Do not:** recolour the tile, stretch or rotate the mark, add outlines or extra shadows, put the lockup on busy imagery, set "tech" in another colour, or typeset "vigiltech" in another font.

## Colour

One pink; everything else is a warm, plum-tinted neutral. See `tokens.json` and the contrast table in `index.html`.

| Name | Hex | Notes |
|---|---|---|
| **VigilTech Pink** (Pink 500) | `#ff0058` | The brand colour. Logo, large display type, filled controls (white text only at 18 px bold and up: 3.9:1). |
| Pink 600 | `#d6004a` | Button fills with white text (5.3:1); body-size pink text on light (5.2:1). |
| Pink 700 | `#a8003a` | Pink **text and links** on light (7.5:1). |
| Pink 400 / 300 | `#ff4d86` / `#ff7aa6` | Pink on dark surfaces (text, links, focus). |
| Pink 900 | `#3d0016` | The deep wine used for vignettes and shadows. |
| Ink / Graphite | `#17101a` / `#6b5d68` | Text and secondary text on light. |
| Bone / Paper | `#f6f1f4` / `#fffbfd` | Light background and surface. |
| Night / Night Raised | `#120a14` / `#1e1422` | Dark appearance. Night is where VigilTech is most at home. |

## Gothic, softly

The pink-and-plum, after-dark look has a quiet gothic streak, taken from church architecture rather than horror. It lives in a few repeatable details:

- **Night first.** Plum-black surfaces with a pink glow low in the frame; light mode is "dawn" (bone and rose).
- **The pointed arch.** The one gothic shape: the lancet window. It is the gloss on the tile, the arches along the wallpaper, and the flame and bowl of the mark. `.vt-lancet` for avatars and hero images.
- **One star.** The four-point star is the accent: the glint on the mark, stars in the sky, `.vt-star` bullets. Use sparingly.
- **Candle-warm light and thin rims.** Highlights lean rose, edges are fine hairlines, shadows are wine, never grey.
- **Never:** skulls as decoration, bats, spikes, blackletter body text, dripping effects. Stay friendly, readable and calm. Accessibility beats atmosphere.

## Typeface: Vigil Sans

An original typeface drawn for VigilTech (`fonts/`, Regular and Bold, TTF and WOFF2, SIL OFL 1.1). The clean, open feel of a modern system sans, plus reading aids from dyslexia-friendly faces: easily confused letters look different (b d p q, I l 1, O 0), bottoms are drawn heavier so each letter sits on the line, apertures are open, spacing is generous. Nothing was traced from another typeface. Use `css/vigilsans.css`. Fall back to the system font; `data-font="system"` is a switch for people who prefer it. A display cut with a subtle gothic flourish is a possible later addition.

## Design language: Golden Gate

Software that feels at home on a Mac and travels well to Windows and Linux. Inspired by the layered, translucent look of modern macOS; no third-party artwork, fonts or marks are used.

1. **Material over decoration.** Bars and sheets are frosted glass (18 px blur, saturated) over the wallpaper; content sits on quiet surfaces.
2. **One tint.** VigilTech Pink marks selection, focus and the primary action. Everything else is neutral.
3. **Soft geometry.** 8 px controls, 12 px groups, 22 px sheets.
4. **Depth from light.** A lit top edge, a darker lower edge, long soft shadows. Never hard black outlines.
5. **Accessible.** 4.5:1 text, a 3 px focus ring, reduced motion and reduced transparency respected, forced-colors supported.

`css/goldengate.css` implements this (tokens, wallpaper, glass toolbar, sidebar, sheet, card, grouped list, buttons, field, segmented control, switch, badge, lancet and star helpers).

## Voice and credits

Plain, warm, specific. Say what the software does; skip hype.
Standard credit: **A product of VigilTech, vigiltech.org.**  Founder line: **VigilTech was founded by Demetria Althea Cohn.**
Product names (AltStack Mail, AltStack Game Producer, Sprite, Box, and so on) stay as product identities until renamed; VigilTech is the company behind them. Keep upstream and third-party notices intact: Godot, Blender, BeepBox and the like are credited by their own licences.

## Sound

`sounds/` is synthesised from scratch by `tools/sound.js` (no samples, GPL v3): `vigil-chime` (startup), `bell` (notifications), `angelus` (a bell pattern for a daily reminder), `kyrie-vigil` (an original melody in the Dorian mode over a drone, for calm backgrounds) and three soft interface sounds. Nothing plays unless the person asks for it.

## Licence

Code and artwork (logos, icons, wallpapers, sounds) are under the **GNU General Public License v3** (`LICENSE`). The typeface Vigil Sans is under the SIL Open Font License 1.1 (`fonts/OFL.txt`), which is compatible with the GPL and lets the font travel inside documents and apps. The name and logo of VigilTech identify the project: use the artwork freely under the GPL, but do not present your work as being made or endorsed by VigilTech.

## Provenance

Logos are Sprite documents: AltStack Sprite's model, saved as `.asprite.json` and exported with its PNG engine. Shapes are generated procedurally (`tools/hd.js`: signed-distance geometry, so each size is drawn natively and never scaled), then opened in Sprite. Sizes beyond Sprite's 512-pixel document limit (1024 px icons, the social card, wallpapers) are drawn at full size and written with Sprite's PNG encoder. Rebuild everything: `node tools/build.js && node tools/site.js` (macOS also produces the `.icns`). The font: `PYTHONPATH=<fonttools> python3 fonts/build_font.py`.
