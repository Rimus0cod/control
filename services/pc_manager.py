"""PC Manager Service — Arch Linux compatible."""

import asyncio
import os
import socket
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from loguru import logger

from config import get_settings

settings = get_settings()


class PCManager:
    """Manages local Arch Linux PC: status, processes, commands, screenshots."""

    # Safe shell commands allowed for non-admin users
    SAFE_COMMANDS = frozenset([
        "ls", "pwd", "whoami", "hostname", "uname",
        "df", "free", "uptime", "date", "ps",
        "ip", "cat", "echo", "lsblk", "lscpu",
    ])

    def __init__(self) -> None:
        self.ip_address = settings.pc_ip_address

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def check_online(self, port: int = 22, timeout: float = 3.0) -> bool:
        """Check if the machine is reachable (SSH port 22 on Linux)."""
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await asyncio.wait_for(
                loop.sock_connect(sock, (self.ip_address, port)),
                timeout=timeout,
            )
            return True
        except Exception:
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> Dict[str, Any]:
        """Return basic system metrics via psutil."""
        try:
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            uptime_sec = int(datetime.now().timestamp() - psutil.boot_time())
            uptime_str = _format_uptime(uptime_sec)

            return {
                "hostname": socket.gethostname(),
                "cpu_percent": cpu,
                "memory_percent": round(mem.percent, 1),
                "memory_used_gb": round(mem.used / 1024 ** 3, 2),
                "memory_total_gb": round(mem.total / 1024 ** 3, 2),
                "disk_percent": round(disk.percent, 1),
                "disk_used_gb": round(disk.used / 1024 ** 3, 2),
                "disk_total_gb": round(disk.total / 1024 ** 3, 2),
                "uptime": uptime_str,
            }
        except Exception as exc:
            logger.error(f"get_system_info error: {exc}")
            return {}

    async def get_running_processes(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Return top processes sorted by memory usage."""
        try:
            procs = []
            for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent", "status"]):
                try:
                    procs.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)
            return procs[:limit]
        except Exception as exc:
            logger.error(f"get_running_processes error: {exc}")
            return []

    async def kill_process(self, pid: int) -> bool:
        """Terminate a process by PID."""
        try:
            psutil.Process(pid).terminate()
            logger.info(f"Process {pid} terminated")
            return True
        except psutil.NoSuchProcess:
            logger.warning(f"Process {pid} not found")
            return False
        except psutil.AccessDenied:
            logger.error(f"Access denied to kill process {pid}")
            return False
        except Exception as exc:
            logger.error(f"kill_process({pid}) error: {exc}")
            return False

    async def get_network_connections(self) -> List[Dict[str, Any]]:
        """Return established TCP connections (limited to 20)."""
        try:
            result = []
            for c in psutil.net_connections(kind="tcp"):
                if c.status == "ESTABLISHED":
                    result.append({
                        "laddr": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                        "raddr": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
                        "pid": c.pid,
                    })
            return result[:20]
        except Exception as exc:
            logger.error(f"get_network_connections error: {exc}")
            return []

    # ------------------------------------------------------------------
    # Power management (Linux / systemd)
    # ------------------------------------------------------------------

    async def reboot(self, delay_minutes: int = 1) -> bool:
        """Schedule a system reboot via systemd shutdown."""
        try:
            cmd = f"shutdown -r +{delay_minutes} 'Reboot initiated via Telegram bot'"
            out = await _run(cmd)
            logger.warning(f"Reboot scheduled in {delay_minutes}m: {out}")
            return True
        except Exception as exc:
            logger.error(f"reboot error: {exc}")
            return False

    async def shutdown(self, delay_minutes: int = 1) -> bool:
        """Schedule system poweroff via systemd shutdown."""
        try:
            cmd = f"shutdown -h +{delay_minutes} 'Shutdown initiated via Telegram bot'"
            out = await _run(cmd)
            logger.warning(f"Shutdown scheduled in {delay_minutes}m: {out}")
            return True
        except Exception as exc:
            logger.error(f"shutdown error: {exc}")
            return False

    async def cancel_shutdown(self) -> bool:
        """Cancel a pending shutdown/reboot."""
        try:
            await _run("shutdown -c")
            return True
        except Exception as exc:
            logger.error(f"cancel_shutdown error: {exc}")
            return False

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    async def execute_command(
        self,
        command: str,
        allowed_commands: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a shell command and return stdout/stderr.

        For non-admin users pass `allowed_commands` to restrict execution
        to the safe whitelist. Admins pass `allowed_commands=None`.
        """
        if allowed_commands is not None:
            base = command.strip().split()[0] if command.strip() else ""
            if base not in self.SAFE_COMMANDS and base not in (allowed_commands or []):
                return {
                    "success": False,
                    "output": "",
                    "error": f"Command '{base}' is not in the allowed list.",
                }

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace").strip()
            error = stderr.decode("utf-8", errors="replace").strip()
            logger.info(f"Command executed: {command!r} → rc={proc.returncode}")
            return {
                "success": proc.returncode == 0,
                "output": output,
                "error": error,
            }
        except asyncio.TimeoutError:
            return {"success": False, "output": "", "error": "Command timed out (30s)"}
        except Exception as exc:
            return {"success": False, "output": "", "error": str(exc)}

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    async def take_screenshot(self) -> Optional[bytes]:
        """
        Capture the current desktop and return raw PNG bytes.

        Tries the following tools in order:
          1. scrot        (lightweight, X11)
          2. import       (ImageMagick, X11)
          3. gnome-screenshot
          4. spectacle    (KDE, headless)
          5. xwd + convert (ImageMagick fallback)

        DISPLAY=:0 and XAUTHORITY are set automatically when missing.
        """
        env = os.environ.copy()
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "XAUTHORITY" not in env:
            for candidate in [
                Path.home() / ".Xauthority",
                Path("/run/user/1000/gdm/Xauthority"),
                Path("/tmp/.Xauthority-1000"),
            ]:
                if candidate.exists():
                    env["XAUTHORITY"] = str(candidate)
                    break

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        tools = [
            f"scrot '{tmp_path}'",
            f"import -window root '{tmp_path}'",
            f"gnome-screenshot -f '{tmp_path}'",
            f"spectacle -b -o '{tmp_path}'",
            f"xwd -root -silent | convert xwd:- '{tmp_path}'",
        ]

        for cmd in tools:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                p = Path(tmp_path)
                if proc.returncode == 0 and p.exists() and p.stat().st_size > 0:
                    data = p.read_bytes()
                    p.unlink(missing_ok=True)
                    logger.info(f"Screenshot captured via: {cmd.split()[0]}")
                    return data
                logger.debug(
                    f"Screenshot tool '{cmd.split()[0]}' failed "
                    f"(rc={proc.returncode}): "
                    f"{stderr.decode(errors='replace').strip()}"
                )
            except Exception as exc:
                logger.debug(f"Screenshot tool exception ({cmd.split()[0]}): {exc}")

        Path(tmp_path).unlink(missing_ok=True)
        logger.error("All screenshot tools failed — install scrot or ImageMagick.")
        return None

    # ------------------------------------------------------------------
    # Systemd services info (Linux)
    # ------------------------------------------------------------------

    async def get_services_status(self) -> List[Dict[str, Any]]:
        """Return status of a few critical systemd services."""
        services = ["NetworkManager", "sshd", "bluetooth", "cups"]
        result = []
        for svc in services:
            out = await _run(f"systemctl is-active {svc}")
            result.append({"name": svc, "status": out.strip()})
        return result


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

async def _run(cmd: str) -> str:
    """Run a shell command, return combined stdout+stderr as string."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (stdout + stderr).decode("utf-8", errors="replace").strip()


def _format_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)