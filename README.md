<p align="center"><img src="brand/vigiltech/icons/os-256.png" alt="VigilOS" width="128"></p>

# VigilOS

**A product of VigilTech, vigiltech.org.** VigilTech was founded by Demetria Althea Cohn.

VigilOS is a desktop for Ubuntu 26.10 ARM64, on KWin Wayland and GTK4, in the VigilTech look: plum-black Night and
warm-bone light appearances, one pink, frosted bars, soft rounded controls. It is development software. The owner
has approved the current desktop appearance; hardware and full application workflow acceptance remain open.

Existing `makos-*` packages, commands, configuration paths, theme names and application IDs keep their names so
upgrades keep working. Renamed from MakkOS on 2026-10-27.

The integration branch repairs the interrupted work delivered at `525fd82`.
See [integration verification](docs/makos/INTEGRATION.md) for the exact checks,
remaining failures and release gates. Older preview evidence does not validate
this expanded code automatically.

Visible apps include Venture, Paper, Digits, Slides, Vigil Box, Studio, Render,
Engine and Sprite. ChatGPT and Claude remain available. Vigil Office is packaged from the unmodified Euro-Office
editors (AGPL-3.0); Paper/Digits/Slides use its upstream wrapper. It is not a built source fork.

## Appearance

- Design system: [brand/vigiltech](brand/vigiltech/BRAND.md) (tokens, Vigil Sans, marks, sounds). GTK 3/4 and Qt themes,
  the shell, Venture, login and boot screens use the same `--vt-*`-derived `@mk_*` tokens.
- Wallpapers, folder icons, app icons and sounds come from the VigilTech macOS kit.
- Night appearance: Settings > Appearance > Night appearance (`dark` in settings.json), or the `MakkOS-Night` GTK theme.
- Every text and background pair is checked at 4.5:1 or better (`tests/test_vigil_contrast.py`).

Build and test commands and recovery steps are in [the developer guide](docs/makos/README.md).
Asset sources and licences are in [ASSETS.md](docs/makos/ASSETS.md).
Keep Plasma and Amerika sessions until owner acceptance; package installation
does not switch the default session, login theme, boot splash or PAM.

Licence: GPL-3.0. Vigil Sans: SIL OFL 1.1.
