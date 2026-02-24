"""Windows PC Management service."""
import asyncio
import socket
from typing import Optional, Dict, Any, List

import psutil
from loguru import logger

from config import get_settings
from utils.validators import validate_command


class PCManager:
    """Windows PC management service."""
    
    def __init__(
        self,
        ip_address: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        domain: Optional[str] = None,
    ):
        """Initialize PC Manager."""
        settings = get_settings()
        
        self.ip_address = ip_address or settings.pc_ip_address
        self.username = username or settings.pc_username
        self.password = password or settings.pc_password
        self.domain = domain or settings.pc_domain
    
    async def check_online(self, port: int = 3389, timeout: float = 3.0) -> bool:
        """
        Check if PC is online.
        
        Args:
            port: Port to check
            timeout: Connection timeout
            
        Returns:
            True if PC is online
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            
            loop = asyncio.get_event_loop()
            await loop.sock_connect(sock, (self.ip_address, port))
            
            sock.close()
            return True
            
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False
    
    async def get_system_info(self) -> Dict[str, Any]:
        """
        Get system information.
        
        Returns:
            Dictionary with system info
        """
        try:
            # Get local system info (if running on same machine)
            info = {
                "hostname": socket.gethostname(),
                "ip_address": self.ip_address,
                "platform": "Windows" if asyncio.platform == "win32" else "Unknown",
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory": psutil.virtual_memory()._asdict(),
                "disk": psutil.disk_usage('/')._asdict(),
            }
            return info
            
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return {"error": str(e)}
    
    async def get_running_processes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get list of running processes.
        
        Args:
            limit: Maximum number of processes to return
            
        Returns:
            List of process dictionaries
        """
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Sort by memory usage
            processes.sort(key=lambda x: x.get('memory_percent', 0), reverse=True)
            return processes[:limit]
            
        except Exception as e:
            logger.error(f"Failed to get processes: {e}")
            return []
    
    async def kill_process(self, pid: int) -> bool:
        """
        Kill a process by PID.
        
        Args:
            pid: Process ID
            
        Returns:
            True if successful
        """
        try:
            process = psutil.Process(pid)
            process.terminate()
            logger.info(f"Process {pid} terminated")
            return True
            
        except psutil.NoSuchProcess:
            logger.warning(f"Process {pid} not found")
            return False
        except psutil.AccessDenied:
            logger.error(f"Access denied to kill process {pid}")
            return False
        except Exception as e:
            logger.error(f"Failed to kill process {pid}: {e}")
            return False
    
    async def execute_command(
        self,
        command: str,
        allowed_commands: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a command on the local system.
        
        Args:
            command: Command to execute
            allowed_commands: Optional whitelist of allowed commands
            
        Returns:
            Dictionary with execution result
        """
        # Validate command for security
        if not validate_command(command, allowed_commands):
            return {
                "success": False,
                "error": "Command not allowed for security reasons",
            }
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            result = {
                "success": process.returncode == 0,
                "returncode": process.returncode,
                "stdout": stdout.decode('utf-8', errors='ignore'),
                "stderr": stderr.decode('utf-8', errors='ignore'),
            }
            
            logger.info(f"Command executed: {command}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute command: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    async def reboot(self) -> bool:
        """
        Reboot the PC (requires admin).
        
        Returns:
            True if command sent successfully
        """
        logger.warning("Initiating system reboot")
        result = await self.execute_command("shutdown /r /t 60 /c 'Reboot initiated by Telegram bot'")
        return result.get("success", False)
    
    async def shutdown(self) -> bool:
        """
        Shutdown the PC (requires admin).
        
        Returns:
            True if command sent successfully
        """
        logger.warning("Initiating system shutdown")
        result = await self.execute_command("shutdown /s /t 60 /c 'Shutdown initiated by Telegram bot'")
        return result.get("success", False)
    
    async def cancel_shutdown(self) -> bool:
        """
        Cancel pending shutdown/reboot.
        
        Returns:
            True if successful
        """
        result = await self.execute_command("shutdown /a")
        return result.get("success", False)
    
    async def get_network_connections(self) -> List[Dict[str, Any]]:
        """
        Get active network connections.
        
        Returns:
            List of network connections
        """
        try:
            connections = []
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'ESTABLISHED':
                    connections.append({
                        "local_address": conn.laddr._asdict() if conn.laddr else None,
                        "remote_address": conn.raddr._asdict() if conn.raddr else None,
                        "status": conn.status,
                        "pid": conn.pid,
                    })
            return connections[:20]  # Limit results
            
        except Exception as e:
            logger.error(f"Failed to get network connections: {e}")
            return []
    
    async def get_services_status(self) -> List[Dict[str, Any]]:
        """
        Get status of Windows services.
        
        Returns:
            List of service dictionaries
        """
        # This would require win32service on Windows
        # For now, return basic info
        return [
            {"name": "Service status unavailable", "status": "requires admin privileges"}
        ]
