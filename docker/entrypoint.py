"""Подготовить каталог весов и запустить воркер от пользователя forecast."""

from __future__ import annotations

import os
import pwd
import sys


def _chown_tree(path: str, uid: int, gid: int) -> None:
    os.chown(path, uid, gid)
    for root, directories, files in os.walk(path):
        for name in directories:
            os.chown(os.path.join(root, name), uid, gid)
        for name in files:
            os.chown(os.path.join(root, name), uid, gid)


def main() -> None:
    hf_home = os.environ.get("HF_HOME", "/opt/hf")
    os.makedirs(hf_home, exist_ok=True)
    if os.geteuid() == 0:
        account = pwd.getpwnam("forecast")
        if os.stat(hf_home).st_uid != account.pw_uid:
            _chown_tree(hf_home, account.pw_uid, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    os.execvp(sys.executable, [sys.executable, "-m", "app.main"])


if __name__ == "__main__":
    main()
