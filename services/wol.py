"""Wake-on-LAN service."""
import socket
import asyncio
from typing import Optional

from loguru import logger

from config import get_settings
from utils.validators import sanitize_mac_address, validate_mac_address


class WakeOnLanService:
    """Wake-on-LAN service for powering on PCs."""
    
    def __init__(
        self,
        mac_address: Optional[str] = None,
        broadcast_address: Optional[str] = None,
    ):
        """Initialize WoL service."""
        settings = get_settings()
        
        self.mac_address = mac_address or settings.pc_mac_address
        self.broadcast_address = broadcast_address or settings.pc_broadcast_address
        
        if not validate_mac_address(self.mac_address):
            raise ValueError(f"Invalid MAC address: {self.mac_address}")
        
        self.mac_address = sanitize_mac_address(self.mac_address)
        
        # Create magic packet
        self.magic_packet = self._create_magic_packet()
    
    def _create_magic_packet(self) -> bytes:
        """
        Create Wake-on-LAN magic packet.
        
        The magic packet is a broadcast frame containing:
        - 6 bytes of 0xFF
        - 16 repetitions of the target MAC address
        """
        # Split MAC address into bytes
        mac_bytes = bytes.fromhex(self.mac_address.replace(':', ''))
        
        # Create magic packet: 6x 0xFF + 16x MAC
        return b'\xff' * 6 + mac_bytes * 16
    
    async def send_magic_packet(self, port: int = 9) -> bool:
        """
        Send Wake-on-LAN magic packet.
        
        Args:
            port: UDP port to send packet to (default 9 for WoL)
            
        Returns:
            True if packet sent successfully
        """
        try:
            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # Send packet in async-friendly way
            loop = asyncio.get_event_loop()
            await loop.sock_sendto(
                sock,
                self.magic_packet,
                (self.broadcast_address, port)
            )
            
            sock.close()
            
            logger.info(
                f"Magic packet sent to {self.mac_address} "
                f"via {self.broadcast_address}:{port}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to send magic packet: {e}")
            return False
    
    async def wake(self, retries: int = 3, delay: float = 1.0) -> bool:
        """
        Send Wake-on-LAN packet with retries.
        
        Args:
            retries: Number of retry attempts
            delay: Delay between retries in seconds
            
        Returns:
            True if at least one packet sent successfully
        """
        for attempt in range(retries):
            logger.info(f"Wake-on-LAN attempt {attempt + 1}/{retries}")
            
            success = await self.send_magic_packet()
            
            if success:
                if attempt > 0:
                    logger.info(f"Wake-on-LAN succeeded on attempt {attempt + 1}")
                return True
            
            if attempt < retries - 1:
                await asyncio.sleep(delay)
        
        logger.error(f"Wake-on-LAN failed after {retries} attempts")
        return False
    
    @staticmethod
    async def check_port_open(
        host: str,
        port: int = 3389,
        timeout: float = 3.0
    ) -> bool:
        """
        Check if a port is open on the target host.
        
        Args:
            host: Target IP address
            port: Port to check (default 3389 for RDP)
            timeout: Connection timeout
            
        Returns:
            True if port is open
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            
            loop = asyncio.get_event_loop()
            result = await loop.sock_connect(sock, (host, port))
            
            sock.close()
            return True
            
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False
    
    async def verify_wake(
        self,
        target_ip: Optional[str] = None,
        port: int = 3389,
        timeout: float = 30.0
    ) -> bool:
        """
        Verify that PC has woken up after sending magic packet.
        
        Args:
            target_ip: Target IP to check
            port: Port to check
            timeout: Maximum time to wait
            
        Returns:
            True if PC is reachable
        """
        settings = get_settings()
        target_ip = target_ip or settings.pc_ip_address
        
        check_interval = 2.0
        elapsed = 0.0
        
        while elapsed < timeout:
            if await self.check_port_open(target_ip, port):
                logger.info(f"PC at {target_ip} is online")
                return True
            
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        logger.warning(f"PC at {target_ip} did not come online within {timeout}s")
        return False
