from __future__ import annotations

import os
import posixpath
from pathlib import Path

import paramiko

LOCAL_ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/nastaunik_club"
SERVICE_NAME = "nastaunik-bot"
EXCLUDE_DIRS = {".venv", "__pycache__", ".git", "logs"}
EXCLUDE_FILES = {"bot.db", "bot_runner.pid"}

SERVICE_FILE = f"""[Unit]
Description=Nastaunik Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory={REMOTE_ROOT}
ExecStart={REMOTE_ROOT}/.venv/bin/python {REMOTE_ROOT}/app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""


def should_upload(path: Path) -> bool:
    rel_parts = path.relative_to(LOCAL_ROOT).parts
    if any(part in EXCLUDE_DIRS for part in rel_parts):
        return False
    if path.is_file() and path.name in EXCLUDE_FILES:
        return False
    if path.suffix == ".pyc":
        return False
    return True


def walk_upload_paths() -> list[Path]:
    return [path for path in LOCAL_ROOT.rglob("*") if should_upload(path)]


def ensure_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    parts = []
    current = remote_dir
    while current not in ("", "/"):
        parts.append(current)
        current = posixpath.dirname(current)
    for directory in reversed(parts):
        try:
            sftp.stat(directory)
        except FileNotFoundError:
            sftp.mkdir(directory)


def upload_tree(sftp: paramiko.SFTPClient) -> None:
    ensure_remote_dir(sftp, REMOTE_ROOT)
    for path in walk_upload_paths():
        rel = path.relative_to(LOCAL_ROOT).as_posix()
        remote_path = posixpath.join(REMOTE_ROOT, rel)
        if path.is_dir():
            ensure_remote_dir(sftp, remote_path)
            continue
        ensure_remote_dir(sftp, posixpath.dirname(remote_path))
        sftp.put(str(path), remote_path)


def run(ssh: paramiko.SSHClient, command: str) -> str:
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if exit_status != 0:
        raise RuntimeError(f"Command failed ({exit_status}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return (out + err).strip()


def write_text_file(sftp: paramiko.SFTPClient, remote_path: str, content: str, mode: int | None = None) -> None:
    ensure_remote_dir(sftp, posixpath.dirname(remote_path))
    with sftp.file(remote_path, "w") as remote_file:
        remote_file.write(content)
    if mode is not None:
        sftp.chmod(remote_path, mode)


def safe_print(value: str) -> None:
    print(value.encode("ascii", errors="replace").decode("ascii"))


def main() -> None:
    host = os.environ["DEPLOY_HOST"]
    username = os.environ["DEPLOY_USER"]
    password = os.environ["DEPLOY_PASSWORD"]

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=host, username=username, password=password, look_for_keys=False, allow_agent=False, timeout=20)

    try:
        sftp = ssh.open_sftp()
        try:
            upload_tree(sftp)
            write_text_file(sftp, f"/etc/systemd/system/{SERVICE_NAME}.service", SERVICE_FILE, mode=0o644)
        finally:
            sftp.close()

        python_check = run(ssh, "bash -lc 'command -v python3 || command -v python'")
        python_bin = python_check.splitlines()[-1].strip() if python_check else "python3"
        if not python_check:
            run(ssh, "bash -lc 'apt-get update && apt-get install -y python3 python3-venv python3-pip'")

        run(ssh, f"bash -lc 'cd {REMOTE_ROOT} && {python_bin} -m venv .venv'")
        run(ssh, f"bash -lc 'cd {REMOTE_ROOT} && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt'")
        run(ssh, f"bash -lc 'systemctl daemon-reload && systemctl enable --now {SERVICE_NAME}.service && systemctl restart {SERVICE_NAME}.service'")

        status = run(ssh, f"bash -lc 'systemctl is-active {SERVICE_NAME}.service && systemctl status {SERVICE_NAME}.service --no-pager -n 20 | cat'")
        safe_print(status)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
