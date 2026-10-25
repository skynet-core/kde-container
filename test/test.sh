#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
runtime=${RUNTIME:-docker}
image=${IMAGE_TAG:-plasma6:local}
shellcheck "$root"/init.d/modules/*.sh "$root"/bin/plasma6-run \
    "$root"/libexec/plasma-session "$root"/libexec/plasma-xserver "$root"/libexec/plasma-vnc
shellcheck "$root"/libexec/plasma-backend/kwin_wayland
shellcheck "$root"/libexec/plasma-host-display
"$runtime" run --rm --user root --entrypoint /usr/bin/python3 \
    --mount "type=bind,source=$root/test,target=/test,readonly" "$image" /test/check-init.py
"$runtime" run --rm --user root --entrypoint /usr/bin/bash "$image" -c \
    'systemd-analyze verify /etc/systemd/system/plasma-*.target /etc/systemd/system/plasma-*.service'
python3 "$root/test/integration.py" --runtime "$runtime" --image "$image" "$@"
