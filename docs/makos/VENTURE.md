# Venture classic chrome and search dismissal

Venture now uses original MakkOS browser chrome: silver navigation buttons, paired
back/forward controls, rounded address and separate search fields, a bookmarks row,
and attached tabs below the navigation area. A local Venture start page is included.
No proprietary browser artwork is used. Browser engine code, certificate checks,
sandbox settings, web content and native identity controls are not replaced.

The launch route is `makos-app venture` → `makos-venture` → the installed
Amerika Venture engine (Firefox fallback). It creates only a MakkOS browser profile
under `$XDG_DATA_HOME/makos/venture` (normally `~/.local/share/makos/venture`).
Existing Firefox/Amerika Venture profiles are not modified or silently migrated.
Bookmarks and sign-ins in those profiles remain there; browser import tools can be
used explicitly. The engine retains its upstream/internal branding. This change
is a browser chrome/profile integration, not a fresh engine source build.

Startup preferences and the stylesheet import have bounded managed sections;
unrelated profile preferences, chrome and bookmark data survive repeat launches.
Toolbar layout is seeded once. The inherited Venture distribution policy hides
bookmarks; this classic stylesheet supplies a fixed bookmarks row in MakkOS only.
The browser chrome is tested against the installed ARM64 158.0.1 engine. Future
engine UI changes may require selector updates. Automation privileges/Marionette
are used only in the isolated test profile and are never enabled by the launcher.

The application-search dismissal fix handles Escape at the overlay's capture phase,
before a focused SearchEntry can consume it. Stop-search and a visible close button
also dismiss the panel. The key rig covers both empty and nonempty application
search and nonempty document search using actual private KWin input events.

Validation commands:

```sh
python3 -m unittest discover -s tests -q
sh tests/rig/makos_settings_rig.sh
sh tests/rig/makos_rig.sh
sh tests/rig/makos_launcher_rig.sh tests/rig/makos_venture_rig.py
```

## Makk OS identity update (dev5)

The launcher now creates a versioned runtime overlay under the Makk cache. Engine
executables are copied unmodified, libraries remain linked to the installed engine,
and only application/distribution/branding resources and the bundled new-tab page
are replaced. New tabs use the same Venture page with Cherry Blossom LLC branding.
The original `/opt/amerika/venture` installation and existing profiles are preserved.
A resource/input fingerprint refreshes the overlay after an engine or asset update.
No production debugging capability is enabled. The runtime resource changes are
published in the Makk OS source; Venture's own repository now builds this identity.

The real-engine rig checked the brand string, a fresh native new tab, the page
identity control on a local HTTP fixture, ordinary tabs and second-launch handoff.
