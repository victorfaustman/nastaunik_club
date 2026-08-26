from __future__ import annotations

import os

import paramiko


def run(ssh: paramiko.SSHClient, command: str) -> str:
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if exit_status != 0:
        raise RuntimeError(f"Command failed ({exit_status}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return (out + err).strip()


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=os.environ["DEPLOY_HOST"],
        username=os.environ["DEPLOY_USER"],
        password=os.environ["DEPLOY_PASSWORD"],
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    try:
        commands = [
            "bash -lc 'systemctl is-active nastaunik-bot.service'",
            "bash -lc 'systemctl status nastaunik-bot.service --no-pager -n 20 | cat'",
            "bash -lc 'journalctl -u nastaunik-bot.service --no-pager -n 20 | cat'",
        ]
        for index, command in enumerate(commands, start=1):
            print(f'--- CHECK {index} ---')
            result = run(ssh, command)
            print(result.encode("ascii", errors="replace").decode("ascii"))
    finally:
        ssh.close()


if __name__ == "__main__":
    main()