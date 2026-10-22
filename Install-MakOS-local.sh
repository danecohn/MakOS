#!/bin/sh
# Install a verified local MakkOS testing channel. No desktop/default/boot switch.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=${1:-$base/apt}
repo=$(CDPATH= cd -- "$repo" && pwd)
script=$base/$(basename -- "$0")
expected=9F52BD98A8EE9096B1BE7AAC1063BBC989A11133
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 26.10 ] || { echo 'This preview targets Ubuntu 26.10 only.' >&2; exit 1; }
[ "$(dpkg --print-architecture)" = arm64 ] || { echo 'This preview is built for ARM64 only.' >&2; exit 1; }
[ -f "$repo/makos-archive-keyring.gpg" ] || { echo 'Pass the extracted signed apt directory as the first argument.' >&2; exit 1; }
fingerprint=$(gpg --batch --with-colons --show-keys "$repo/makos-archive-keyring.gpg" 2>/dev/null | awk -F: '$1=="fpr" {print $10;exit}')
[ "$fingerprint" = "$expected" ] || { echo 'The archive signing identity does not match.' >&2; exit 1; }
gpgv --keyring "$repo/makos-archive-keyring.gpg" "$repo/dists/makos-testing/InRelease"
if [ "$(id -u)" -ne 0 ]; then
  exec pkexec /bin/sh "$script" "$repo"
fi
dest=/var/lib/makos/local-apt/0.1.0-dev.6
install -d -m 0755 "$dest" /usr/share/keyrings
cp -a "$repo/." "$dest/"
install -m 0644 "$dest/makos-archive-keyring.gpg" /usr/share/keyrings/makos-archive-keyring.gpg
cat > /etc/apt/sources.list.d/makos-local.sources <<EOF
Types: deb
URIs: file:$dest
Suites: makos-testing
Components: main
Architectures: arm64
Signed-By: /usr/share/keyrings/makos-archive-keyring.gpg
EOF
apt-get update -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/makos-local.sources -o Dir::Etc::sourceparts=-
apt-get install --no-remove --no-install-recommends makos-desktop=0.1.0~dev6
printf '\nMakk OS is available in the login session selector. Log out normally and select Makk OS.\nTo return, choose Plasma or Amerika OS. Login and boot defaults were not changed.\n'
