# MakkOS development preview

VigilOS is a VigilTech desktop for Ubuntu ARM64 on KWin Wayland.
**This is an early installable development preview, not a completed desktop.**
Do not remove fallback desktops or everyday file tools on the strength of this preview.
The owner has approved the current desktop appearance. Full app compatibility
and hardware acceptance remain open.

## Integration status

See [INTEGRATION.md](INTEGRATION.md) for current evidence. The handoff added larger
Files, Settings, Seek, Launcher Bar and native-app implementations. Their presence
in the tree is not proof of completeness. The integration checks are being rerun
against source and extracted ARM64 packages before deployment.

The source includes 55 original AI app/folder/file/drive icons and six original
wallpapers. Wallpaper output is explicitly resampled to 3840×2160; see provenance.
Settings and Studio-suite icons currently use original vector development art.
Paper/Digits/Slides use Vigil Office's unmodified Euro-Office wrapper, with the
upstream AGPL notices and identity retained. A source fork and full app reskin
remain open work.

## Release gates

Owner-confirmed normal login; physical touch/pen, scaling, battery and accessibility
acceptance; complete launcher/Spread/Desks input tests; universal menu export and
third-party skins; safe login/boot snapshot/revert/recovery; all Settings apply paths
on hardware; complete core-app/media/file workflows; Office edit/save/reopen and
styling acceptance. The themes and their rig galleries alone do not establish
that the normal session applies every third-party style correctly.

Do not remove fallback sessions or broad sets of installed applications yet.

## Build and test

Run from this repository:

```sh
python3 tools/make_makos_vectors.py
python3 tools/ingest_makos_assets.py --normalize
python3 -m unittest discover -s tests -q
sh tests/rig/makos_rig.sh
python3 tools/build_makos.py --no-repo
```

The output of the private rig is evidence for that rig only. It does not establish
that the owner's normal session, all real apps, physical touch/pen or login/boot works.

## Try and return

After inspecting the verification report, install only the local MakkOS packages with
the provided installer. It does not remove apps, stop the current desktop, select a
default session, modify PAM or enable any login/boot theme. Finish current work,
log out normally, choose **MakkOS** in the login screen's session selector and log in.

To return: log out, choose **Plasma (Wayland)** or **Amerika OS**, and log in.
If MakkOS is blank, press Ctrl+Alt+F3, log in yourself and inspect:

```sh
tail -100 ~/.local/state/makos/shell.log
```

To uninstall (keep configuration for recovery):

```sh
sudo apt remove makos-desktop makos-apps makos-shell makos-session makos-theme makos-icons
```

Do not run `apt autoremove` as part of this cleanup: the previous desktop metapackage
was removed together with the explicitly unwanted Agent; retained packages are marked
manual to protect the fallback. No real `.claude`, `.codex` or `.openclaw` config is modified.

## Cleanup decision

The user explicitly requested removal of Amerika Agent/OpenClaw. Its user services
were stopped/disabled and its package removed, along with the dependent metapackage.
About 359 MB of installed files were removed. Existing user data was left untouched;
no secret store or `.openclaw` directory was inspected. ChatGPT, Claude, Studio suite,
KWin, Plasma and Amerika session packages are preserved. Broad package cleanup is
pending MakkOS completion and verification. Curated MakkOS launcher presentation is
separate from claiming that all other packages have been uninstalled.
