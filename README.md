# MakkOS

Renamed from MakOS on 2026-10-22. Existing `makos-*` packages, commands,
configuration paths and application IDs remain stable for upgrades.

An original Glass & Metal desktop for Ubuntu 26.10 ARM64, using KWin Wayland and
GTK4. This is development software. The owner has approved the current desktop appearance;
hardware and full application workflow acceptance remain open.

The integration branch repairs the interrupted work delivered at `525fd82`.
See [integration verification](docs/makos/INTEGRATION.md) for the exact checks,
remaining failures and release gates. Older preview evidence does not validate
this expanded code automatically.

Visible apps include Venture, Paper, Digits, Slides, MakBox, Studio, Render,
Engine and Sprite. ChatGPT and Claude remain available. Mak Office is an Amerika
LLC product packaged from the unmodified Euro-Office editors (AGPL-3.0);
Paper/Digits/Slides use its upstream wrapper. It is not a built source fork.

Build and test commands and recovery steps are in [the developer guide](docs/makos/README.md).
Asset sources and licences are in [ASSETS.md](docs/makos/ASSETS.md).
Keep Plasma and Amerika sessions until owner acceptance; package installation
does not switch the default session, login theme, boot splash or PAM.
