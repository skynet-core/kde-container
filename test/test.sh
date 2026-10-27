#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
runtime=${RUNTIME:-docker}
image=${IMAGE_TAG:-plasma6:local}
# A test-target image must never be published as the production image.
"$runtime" run --rm --entrypoint /usr/bin/python3 "$image" -c '
import shutil
assert not any(shutil.which(name) for name in ("chromium", "chromium-browser")), "Chromium belongs only in ui-test"
'
python3 "$root/test/unit.py"
shellcheck "$root"/init.d/modules/*.sh "$root"/bin/plasma6-run \
	"$root"/libexec/plasma-{session,xserver,vnc,host-display,software-display} \
	"$root"/libexec/plasma-backend/kwin_wayland
"$runtime" run --rm --user root --entrypoint /usr/bin/python3 \
	--mount "type=bind,source=$root/test,target=/test,readonly" "$image" /test/check-init.py
"$runtime" run --rm --user root --entrypoint /usr/bin/bash "$image" -c \
	'systemd-analyze verify /etc/systemd/system/plasma-*.target /etc/systemd/system/plasma-*.service'
python3 "$root/test/integration.py" --runtime "$runtime" --image "$image" "$@"
