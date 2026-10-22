# Makk OS development rules

MakkOS is an original Linux desktop on KWin Wayland, ARM64 first. Work in `src/makos`.
Keep the existing Plasma and Amerika sessions until MakkOS passes owner acceptance.
The owner authorized this project's lead agent to push and publish; mark previews honestly.
Do not claim completion, physical 60 fps, a working login, or hardware acceptance from a rig run.

Never copy proprietary operating-system artwork, fonts, sounds, cursors or logos. Keep
asset provenance in `docs/makos/ASSETS.md`. Preserve upstream credits and licences.
Visible app names: Venture, Paper, Digits, MakBox, Studio, Render, Engine, Sprite.
Keep ChatGPT and Claude available. Amerika Agent/OpenClaw was explicitly removed.

Never read, print or modify the real `.claude`, `.codex`, or `.openclaw` configuration.
Never ask for or log credentials. Let system authentication agents own privileged prompts.
Never commit signing keys or tokens. A local signing identity is used through GPG only.

After each shell or theme edit, run `sh tests/rig/makos_rig.sh`: it uses a private D-Bus,
KWin, runtime/config/home and screenshot authorization. Check logs and actual screenshots.
`python3 -m unittest discover -s tests -q` covers pure logic and package boundaries.
KWin ScreenShot2 v5 hides the caller by default: shell screenshots must explicitly include it.

Build only MakkOS packages with `python3 build.py --no-repo`. Generated materials, icons,
cursors and sounds are derivatives; the build regenerates them. To compile cursors set
`MAKOS_XCURSORGEN` or provide the distro's xcursorgen (x11-apps) build tool.
No login/boot/PAM/default-session mutations in package installation. Risky optional theme
switches require their own tested snapshot/revert/recovery implementation before exposure.

Current identity: Makk OS, developed by Cherry Blossom LLC; shared original cherry blossom logo.
Makk Office must use Euro-Office as its direct upstream. Preserve licence notices.
Login/boot changes are explicitly authorized by the owner on 2026-10-22, but require tested recovery.

Encrypted-root regression (2026-10-22): do not regenerate boot images without
cryptsetup-initramfs/LVM support and matching active crypttab mapping. Run
`pkexec /usr/sbin/makk-boot-check` before/after boot changes. Never restore the
original before-k2xmgz66 initrds without validation: they predate disk-unlock repair.
Retain the working Surface kernel and its touchscreen DTB. Do not equate the
generic kernel successfully unlocking disk with Surface input-driver support.
