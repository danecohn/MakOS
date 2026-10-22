# Integration audit of the interrupted handoff

Baseline: upstream `main` at `525fd82f77cd516fb8480e7521ba22305c0e29f4`.
Target: Ubuntu 26.10 ARM64. This audit is development evidence, not owner acceptance.
The handoff's per-agent partial documents were not present in that commit: only
ARCHITECTURE.md, ASSETS.md, README.md and SOURCES.md existed under docs/makos.

## Repairs

* Recovered all 55 original AI icon inputs and six wallpaper inputs from the preserved
  verified-preview branch. The handoff retained only nine inputs. Builds now require
  the complete set and regenerate derivatives, six wallpapers, cursors and sounds.
* Restored selective builds, package extraction smoke, fail-fast shell-rig execution,
  private D-Bus activation environment and the startup-ready watchdog. A zero exit
  before ready now counts as a startup failure, with bounded retries back to login.
* Files and Settings launch in separate processes, protecting the shell from app
  crashes. The test rig explicitly embeds them only for widget introspection.
* Launcher Bar magnification snaps fully to rest; its moving tooltips use whole
  pixels to avoid invalid pixman rectangles. Packaged wallpaper lookup accepts the
  shipped JPEG, and a regression checks for a blank background.
* Smaller yielded directory batches remove long main-loop stalls on the 30,000-file
  fixture. Preview scrolling and bounded metadata labels avoid oversized layouts.
* Activity preserves selection across refresh. Text Editor replaces text as an
  undoable edit without GTK irreversible-action warnings. Screenshot initializes its
  controls before changing modes. Tunes uses supported GApplication flags.
* Fixed integration fixtures: real GTK app IDs, private menu registrar, async
  self-hosted MPRIS requests, targeted Settings switches, stable Quick Look identity,
  deterministic calculator expression, playback state and test-process cleanup.
* Recovered GTK/KWin/Python version dependencies; package both Settings and Software
  Center helpers/polkit policies; include cursor and sound payloads, omit bytecode.
* Paper, Digits and Slides use Mak Office's Euro-Office wrapper and upstream
  StartupWMClass. The shell preload is removed before spawning it; the wrapper owns
  its separate CEF preload. makos-apps recommends mak-office.

## Installed system

Installed mak-office 0.3.0-1, updated its amerika-office transitional package and
installed fonts-crosextra-carlito. APT removed no packages. The three editor modes
rendered real windows and compositor pixels under the private KWin/XWayland rig.
The program remains the unmodified upstream editor; no source-fork claim is made.
No sandbox relaxation or AppArmor profile was required for this check.

MakOS itself has not been installed or selected in the normal session by this audit.
Login/boot themes, PAM and desktop defaults remain unchanged. Keep fallback sessions.
Railway and Social production services were not deployed.

## Remaining acceptance

A normal owner login, Office edit/save/reopen, physical input/scaling/accessibility,
third-party styling and global menus, all Files/media workflows, hardware Settings
mutations, complete Launcher Bar/Spread/Desks input checks, and tested login/boot
snapshot/revert/recovery remain release gates. Do not call the full product finished
until the owner confirms it. No package release is published by this repair audit.

## Verified results

* 157 standalone unit tests: pass, 10 skips (the isolated Files tests run inside
  their own subprocess as part of this suite).
* Source shell smoke: ready, actual captures, no Traceback/CRITICAL/CSS parser error.
* Main GTK integration: tabs/views, appearance, reduce motion, real DBusMenu click,
  notifications and frame sampling pass.
* Files UI: 38 checks pass, including copy/move/conflicts/undo/trash/tags/archives,
  column/cover/list/icon views, previews, tabs, permissions and 30,000-file loading.
  Latest measured load 4.51 seconds, worst main-thread gap 147 ms (private fixture).
* Settings: all 21 panes build with fixtures, selected backend apply paths pass;
  real read-only pane probes pass. Seek's private indexing/live updates/settings/
  file preview integration passes. These are not physical hardware apply acceptance.
* Native apps: 15 behavior groups pass; 12 separate-process launches, menu
  registration, Screenshot file creation and Widgets overlay pass. Sprite launcher
  stayed alive in the private rig; its full workflow remains unverified.
* Launcher Bar: nine real pointer/state/timing checks pass with the normal renderer
  and labels enabled. Spread/Desks/gestures have not received equivalent coverage.
* Extracted six-package payload: shell ready; Files and Settings have independent
  PIDs; inspected compositor capture includes the wallpaper and all Settings rows.
* Mak Office: installed ARM64 wrapper renders word/cell/slide editor windows and
  nonblank compositor captures in private KWin/XWayland. Save/reopen not tested.
* Theme galleries produced GTK3/GTK4/Qt/notification/decoration captures at 1x and
  a decoration capture at 2x. This diagnostic script currently masks some command
  errors; treat the galleries as visual evidence, not a comprehensive passing test.
* Signed local APT index verifies against archive fingerprint
  `9F52BD98A8EE9096B1BE7AAC1063BBC989A11133`. Sandbox dependency simulation resolves
  all six dev2 packages with zero removals. No MakOS packages installed by the audit.

Frame callbacks are virtual-output evidence only; no physical-display 60 fps claim.
The normal session and hardware gates above remain open.


Source repair commit `b04549fe256142e9a3bb8f5ab7041f78b39f5a05` passed
[GitHub Source checks](https://github.com/danecohn/MakOS/actions/runs/39780189648).
The local dev2 archive is staged for review and has not been published as a GitHub
package release. `Install-MakOS-local.sh` verifies its signed index before asking
the system authentication agent to install it. It refuses package removals.
