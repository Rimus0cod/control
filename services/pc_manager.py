"""PC Manager Service — Cross-platform (Windows/Linux)."""

import asyncio
import os
import platform
import shlex
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
    """Manages local PC: status, processes, commands, screenshots.
    
    Supports both Windows and Linux operating systems.
    """

    # Safe shell commands allowed for non-admin users
    SAFE_COMMANDS_LINUX = frozenset([
        "ls", "pwd", "whoami", "hostname", "uname",
        "df", "free", "uptime", "date", "ps",
        "ip", "cat", "echo", "lsblk", "lscpu",
    ])
    
    SAFE_COMMANDS_WINDOWS = frozenset([
        "dir", "cd", "type", "ipconfig", "hostname",
        "systeminfo", "ver", "whoami", "netstat", "tasklist",
    ])

    def __init__(self) -> None:
        self.ip_address = settings.pc_ip_address
        self.os_type = self._detect_os()
        
    def _detect_os(self) -> str:
        """Detect the operating system."""
        return platform.system().lower()  # 'windows' or 'linux'
    
    def _is_windows(self) -> bool:
        return self.os_type == "windows"
    
    def _is_linux(self) -> bool:
        return self.os_type == "linux"

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def check_online(self, port: int = 22, timeout: float = 3.0) -> bool:
        """Check if the machine is reachable."""
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
            uptime_str = self._format_uptime(uptime_sec)

            info = {
                "hostname": socket.gethostname(),
                "os": platform.system(),
                "os_version": platform.version() if self._is_windows() else platform.release(),
                "cpu_percent": cpu,
                "memory_percent": round(mem.percent, 1),
                "memory_used_gb": round(mem.used / 1024 ** 3, 2),
                "memory_total_gb": round(mem.total / 1024 ** 3, 2),
                "disk_percent": round(disk.percent, 1),
                "disk_used_gb": round(disk.used / 1024 ** 3, 2),
                "disk_total_gb": round(disk.total / 1024 ** 3, 2),
                "uptime": uptime_str,
            }
            
            # Add battery info if available
            try:
                battery = psutil.sensors_battery()
                if battery:
                    info["battery_percent"] = round(battery.percent, 1)
                    info["battery_charging"] = battery.power_plugged
                    info["battery_time_left"] = battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else None
            except (AttributeError, Exception):
                pass  # No battery or not available
                
            return info
        except Exception as exc:
            logger.error(f"get_system_info error: {exc}")
            return {}

    async def collect_data(self) -> Dict[str, Any]:
        """Collect comprehensive PC data including all stats."""
        try:
            # Basic system info
            system_info = await self.get_system_info()
            
            # Running processes
            processes = await self.get_running_processes(limit=20)
            
            # Network connections
            network = await self.get_network_connections()
            
            # Disk partitions
            partitions = await self.get_disk_partitions()
            
            # Network interfaces
            net_if = await self.get_network_interfaces()
            
            return {
                "system": system_info,
                "processes": processes,
                "network_connections": network,
                "disk_partitions": partitions,
                "network_interfaces": net_if,
                "collected_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error(f"collect_data error: {exc}")
            return {"error": str(exc)}

    async def get_disk_partitions(self) -> List[Dict[str, Any]]:
        """Get all disk partitions."""
        try:
            partitions = []
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    partitions.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / 1024 ** 3, 2),
                        "used_gb": round(usage.used / 1024 ** 3, 2),
                        "free_gb": round(usage.free / 1024 ** 3, 2),
                        "percent": round(usage.percent, 1),
                    })
                except PermissionError:
                    pass
            return partitions
        except Exception as exc:
            logger.error(f"get_disk_partitions error: {exc}")
            return []

    async def get_network_interfaces(self) -> List[Dict[str, Any]]:
        """Get network interface information."""
        try:
            interfaces = []
            net_if = psutil.net_io_counters(pernic=True)
            for iface, counters in net_if.items():
                interfaces.append({
                    "name": iface,
                    "bytes_sent": counters.bytes_sent,
                    "bytes_recv": counters.bytes_recv,
                    "packets_sent": counters.packets_sent,
                    "packets_recv": counters.packets_recv,
                    "errin": counters.errin,
                    "errout": counters.errout,
                })
            return interfaces
        except Exception as exc:
            logger.error(f"get_network_interfaces error: {exc}")
            return []

    async def get_running_processes(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Return top processes sorted by memory usage."""
        try:
            procs = []
            for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent", "status", "username"]):
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

    async def kill_process_by_name(self, name: str) -> int:
        """Terminate all processes matching the name. Returns count of killed processes."""
        killed = 0
        try:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if name.lower() in p.info["name"].lower():
                        psutil.Process(p.info["pid"]).terminate()
                        killed += 1
                        logger.info(f"Process {p.info['pid']} ({p.info['name']}) terminated")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as exc:
            logger.error(f"kill_process_by_name({name}) error: {exc}")
        return killed

    async def get_process_by_pid(self, pid: int) -> Optional[Dict[str, Any]]:
        """Get detailed info about a specific process."""
        try:
            p = psutil.Process(pid)
            return {
                "pid": p.pid,
                "name": p.name(),
                "status": p.status(),
                "username": p.username(),
                "cpu_percent": p.cpu_percent(interval=0.1),
                "memory_percent": p.memory_percent(),
                "memory_info": p.memory_info()._asdict(),
                "create_time": p.create_time(),
                "cmdline": p.cmdline(),
            }
        except psutil.NoSuchProcess:
            return None
        except Exception as exc:
            logger.error(f"get_process_by_pid({pid}) error: {exc}")
            return None

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
                        "status": c.status,
                    })
            return result[:20]
        except Exception as exc:
            logger.error(f"get_network_connections error: {exc}")
            return []

    # ------------------------------------------------------------------
    # Power management (Windows / Linux)
    # ------------------------------------------------------------------

    async def reboot(self, delay_minutes: int = 1) -> bool:
        """Schedule a system reboot."""
        try:
            if self._is_windows():
                # Windows: shutdown /r /t <seconds>
                delay_seconds = delay_minutes * 60
                cmd = f"shutdown /r /t {delay_seconds} /c \"Reboot initiated via Telegram bot\""
            else:
                # Linux: shutdown -r +<minutes>
                cmd = f"shutdown -r +{delay_minutes} 'Reboot initiated via Telegram bot'"
            
            await self._run_cmd(cmd)
            logger.warning(f"Reboot scheduled in {delay_minutes}m")
            return True
        except Exception as exc:
            logger.error(f"reboot error: {exc}")
            return False

    async def shutdown(self, delay_minutes: int = 1) -> bool:
        """Schedule system poweroff."""
        try:
            if self._is_windows():
                # Windows: shutdown /s /t <seconds>
                delay_seconds = delay_minutes * 60
                cmd = f"shutdown /s /t {delay_seconds} /c \"Shutdown initiated via Telegram bot\""
            else:
                # Linux: shutdown -h +<minutes>
                cmd = f"shutdown -h +{delay_minutes} 'Shutdown initiated via Telegram bot'"
            
            await self._run_cmd(cmd)
            logger.warning(f"Shutdown scheduled in {delay_minutes}m")
            return True
        except Exception as exc:
            logger.error(f"shutdown error: {exc}")
            return False

    async def sleep(self) -> bool:
        """Put the system to sleep/hibernate."""
        try:
            if self._is_windows():
                # Windows: use rundll32 for sleep
                cmd = "rundll32.exe powrprof.dll,SetSuspendState 0,0,0"
            else:
                # Linux: systemctl suspend or pm-suspend
                try:
                    cmd = "systemctl suspend"
                except:
                    cmd = "pm-suspend"
            
            await self._run_cmd(cmd)
            logger.info("System sleep initiated")
            return True
        except Exception as exc:
            logger.error(f"sleep error: {exc}")
            return False

    async def hibernate(self) -> bool:
        """Put the system into hibernate mode."""
        try:
            if self._is_windows():
                cmd = "rundll32.exe powrprof.dll,SetSuspendState 1,0,0"
            else:
                # Linux hibernate (requires swap)
                cmd = "systemctl hibernate"
            
            await self._run_cmd(cmd)
            logger.info("System hibernate initiated")
            return True
        except Exception as exc:
            logger.error(f"hibernate error: {exc}")
            return False

    async def cancel_shutdown(self) -> bool:
        """Cancel a pending shutdown/reboot."""
        try:
            if self._is_windows():
                cmd = "shutdown /a"
            else:
                cmd = "shutdown -c"
            
            await self._run_cmd(cmd)
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
        Execute a command and return stdout/stderr.

        Shell features are intentionally disabled so that command allowlists
        cannot be bypassed via substitutions, pipes, or redirections.
        """
        if not command or not command.strip():
            return {
                "success": False,
                "output": "",
                "error": "Command is empty.",
            }

        try:
            tokens = shlex.split(command, posix=not self._is_windows())
        except ValueError as exc:
            return {
                "success": False,
                "output": "",
                "error": f"Invalid command syntax: {exc}",
            }

        if not tokens:
            return {
                "success": False,
                "output": "",
                "error": "Command is empty.",
            }

        if allowed_commands is not None:
            safe_commands = self.SAFE_COMMANDS_WINDOWS if self._is_windows() else self.SAFE_COMMANDS_LINUX
            base = tokens[0]
            if base not in safe_commands and base not in (allowed_commands or []):
                return {
                    "success": False,
                    "output": "",
                    "error": f"Command '{base}' is not in the allowed list.",
                }

        try:
            proc = await asyncio.create_subprocess_exec(
                *tokens,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace").strip()
            error = stderr.decode("utf-8", errors="replace").strip()
            logger.info(f"Command executed: {tokens!r} → rc={proc.returncode}")
            return {
                "success": proc.returncode == 0,
                "output": output,
                "error": error,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"success": False, "output": "", "error": "Command timed out (30s)"}
        except FileNotFoundError:
            return {
                "success": False,
                "output": "",
                "error": f"Command '{tokens[0]}' was not found.",
            }
        except Exception as exc:
            return {"success": False, "output": "", "error": str(exc)}

    # ------------------------------------------------------------------
    # Screenshot (Cross-platform)
    # ------------------------------------------------------------------

    async def take_screenshot(self) -> Optional[bytes]:
        """Capture the current desktop and return raw PNG bytes.
        
        Tries different methods based on OS:
        - Windows: mss, pyautogui, PIL
        - Linux: scrot, import, gnome-screenshot, etc.
        """
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Try mss (works on both Windows and Linux)
            data = await self._screenshot_mss(tmp_path)
            if data:
                return data
            
            # Try pyautogui
            data = await self._screenshot_pyautogui(tmp_path)
            if data:
                return data
                
            # OS-specific methods
            if self._is_windows():
                data = await self._screenshot_windows_pil(tmp_path)
            else:
                data = await self._screenshot_linux_tools(tmp_path)
            
            if data:
                return data
                
        finally:
            # Cleanup
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except:
                pass
        
        logger.error("All screenshot methods failed")
        return None

    async def _screenshot_mss(self, path: str) -> Optional[bytes]:
        """Try using mss library."""
        try:
            import mss
            
            with mss.mss() as sct:
                # Grab the full screen
                sct_img = sct.grab(sct.monitors[0])
                # Convert to PNG bytes
                img_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
                
            if img_bytes:
                logger.info("Screenshot captured via mss")
                return img_bytes
        except ImportError:
            logger.debug("mss not installed")
        except Exception as exc:
            logger.debug(f"mss screenshot failed: {exc}")
        return None

    async def _screenshot_pyautogui(self, path: str) -> Optional[bytes]:
        """Try using pyautogui."""
        try:
            import pyautogui
            
            img = pyautogui.screenshot()
            if img:
                img.save(path)
                p = Path(path)
                if p.exists() and p.stat().st_size > 0:
                    logger.info("Screenshot captured via pyautogui")
                    return p.read_bytes()
        except ImportError:
            logger.debug("pyautogui not installed")
        except Exception as exc:
            logger.debug(f"pyautogui screenshot failed: {exc}")
        return None

    async def _screenshot_windows_pil(self, path: str) -> Optional[bytes]:
        """Windows-specific screenshot using PIL."""
        try:
            from PIL import ImageGrab
            
            img = ImageGrab.grab()
            if img:
                img.save(path)
                p = Path(path)
                if p.exists() and p.stat().st_size > 0:
                    logger.info("Screenshot captured via PIL/ImageGrab")
                    return p.read_bytes()
        except ImportError:
            logger.debug("PIL not installed")
        except Exception as exc:
            logger.debug(f"PIL screenshot failed: {exc}")
        return None

    async def _screenshot_linux_tools(self, path: str) -> Optional[bytes]:
        """Linux-specific screenshot tools."""
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

        tools = [
            f"scrot '{path}'",
            f"import -window root '{path}'",
            f"gnome-screenshot -f '{path}'",
            f"spectacle -b -o '{path}'",
            f"xwd -root -silent | convert xwd:- '{path}'",
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
                p = Path(path)
                if proc.returncode == 0 and p.exists() and p.stat().st_size > 0:
                    data = p.read_bytes()
                    logger.info(f"Screenshot captured via: {cmd.split()[0]}")
                    return data
                logger.debug(f"Screenshot tool '{cmd.split()[0]}' failed")
            except Exception as exc:
                logger.debug(f"Screenshot tool exception: {exc}")

        return None

    # ------------------------------------------------------------------
    # Systemd services info (Linux) / Windows Services
    # ------------------------------------------------------------------

    async def get_services_status(self) -> List[Dict[str, Any]]:
        """Return status of system services."""
        if self._is_windows():
            return await self._get_windows_services()
        else:
            return await self._get_linux_services()

    async def _get_windows_services(self) -> List[Dict[str, Any]]:
        """Get Windows services status."""
        services = ["Spooler", "W32Time", "BITS", "wuauserv", "Dhcp"]
        result = []
        for svc in services:
            try:
                proc = await asyncio.create_subprocess_shell(
                    f'sc query {svc}',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                output = stdout.decode("utf-8", errors="replace")
                status = "running" if "RUNNING" in output else "stopped"
                result.append({"name": svc, "status": status})
            except:
                result.append({"name": svc, "status": "unknown"})
        return result

    async def _get_linux_services(self) -> List[Dict[str, Any]]:
        """Get Linux services status."""
        services = ["NetworkManager", "sshd", "bluetooth", "cups"]
        result = []
        for svc in services:
            out = await self._run_cmd(f"systemctl is-active {svc}")
            result.append({"name": svc, "status": out.strip()})
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _run_cmd(self, cmd: str) -> str:
        """Run a shell command, return combined stdout+stderr as string."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (stdout + stderr).decode("utf-8", errors="replace").strip()

    def _format_uptime(self, seconds: int) -> str:
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
