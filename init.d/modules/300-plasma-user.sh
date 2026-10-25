#!/usr/bin/bash
# Adjust only the desktop account; systemd must still start as container root.

module_plasma_user_enabled() {
    [[ -n ${PLASMA_UID:-}${PLASMA_GID:-} ]]
}

module_plasma_user_run() {
    [[ $(id -u) == 0 ]] || die 'Run PID 1 as root; use --user=0:0 with Podman keep-id'
    local old_uid old_gid uid gid owner value
    old_uid=$(id -u plasma)
    old_gid=$(id -g plasma)
    uid=${PLASMA_UID:-$old_uid}
    gid=${PLASMA_GID:-$old_gid}
    for value in "$uid" "$gid"; do
        if [[ ! $value =~ ^[1-9][0-9]{0,9}$ ]] || (( value > 4294967294 )); then
            die 'PLASMA_UID and PLASMA_GID must be nonzero numeric IDs below 4294967295'
        fi
    done
    owner=$(getent passwd "$uid" | cut -d: -f1) || true
    [[ -z $owner || $owner == plasma ]] || die "PLASMA_UID $uid already belongs to '$owner'"
    if [[ $gid != "$old_gid" ]] && ! getent group "$gid" >/dev/null; then
        groupmod --gid "$gid" plasma
    fi
    if [[ $uid != "$old_uid" || $gid != "$old_gid" ]]; then
        # usermod also updates files owned by the old IDs inside the home.
        usermod --uid "$uid" --gid "$gid" plasma
        chown "$uid:$gid" /home/plasma
        if [[ $gid != "$old_gid" ]]; then
            find /home/plasma -xdev -gid "$old_gid" -exec chgrp --no-dereference "$gid" {} +
        fi
    fi
    info "Plasma identity: uid=$uid gid=$gid"
}
