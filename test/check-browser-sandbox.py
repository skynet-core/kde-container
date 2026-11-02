"""Render a Chromium document when host policy denies unprivileged userns.

Run as root inside a disposable privileged container; the filter applies only
to the browser subtree. NoNewPrivs must stay zero so its SUID helper can run.
"""

import ctypes
import errno
import json
import os
import platform
import pwd
import shutil
import subprocess
import tempfile


def restrict_and_drop():
    assert platform.machine() == "x86_64", "The syscall table below is x86_64"

    class Filter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint32),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("filters", ctypes.POINTER(Filter))]

    # clone=56, unshare=272, clone3=435. ENOSYS makes clone3 callers use
    # clone, whose CLONE_NEWUSER argument classic BPF can inspect.
    rules = (Filter * 10)(
        Filter(0x20, 0, 0, 0),
        Filter(0x15, 3, 0, 56),
        Filter(0x15, 2, 0, 272),
        Filter(0x15, 3, 0, 435),
        Filter(0x06, 0, 0, 0x7FFF0000),
        Filter(0x20, 0, 0, 16),
        Filter(0x45, 2, 1, 0x10000000),
        Filter(0x06, 0, 0, 0x00050000 | errno.ENOSYS),
        Filter(0x06, 0, 0, 0x7FFF0000),
        Filter(0x06, 0, 0, 0x00050000 | errno.EPERM),
    )
    program = Program(len(rules), rules)
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(39, 0, 0, 0, 0) == 0, "NoNewPrivs prevents SUID fallback"
    assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0, ctypes.get_errno()
    account = pwd.getpwnam("plasma")
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    assert libc.prctl(39, 0, 0, 0, 0) == 0
    ctypes.set_errno(0)
    assert libc.unshare(0x10000000) == -1 and ctypes.get_errno() == errno.EPERM
    os.write(2, b"Verified: plasma userns=EPERM, NoNewPrivs=0\n")


def main():
    marker = "sandbox-fallback-renders-document"
    account = pwd.getpwnam("plasma")
    browser = shutil.which("chromium-browser") or shutil.which("chromium")
    assert browser, "The ui-test image must contain Chromium"
    with tempfile.TemporaryDirectory(prefix="chromium-sandbox-") as profile:
        os.chown(profile, account.pw_uid, account.pw_gid)
        result = subprocess.run(
            [
                browser,
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                "--dump-dom",
                f"data:text/html,<title>{marker}</title><p>{marker}</p>",
            ],
            preexec_fn=restrict_and_drop,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={**os.environ, "HOME": account.pw_dir},
        )
    print(
        json.dumps(
            {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        ),
        flush=True,
    )
    assert result.returncode == 0, "Chromium failed with its sandbox enabled"
    assert marker in result.stdout, "Chromium did not render the document"
    print("PASS Chromium sandbox fallback with user namespaces denied")


if __name__ == "__main__":
    main()
