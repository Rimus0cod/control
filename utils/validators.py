"""Input validators."""
import ipaddress
import re
from typing import Optional


def validate_mac_address(mac: str) -> bool:
    """
    Validate MAC address format.
    
    Args:
        mac: MAC address string
        
    Returns:
        True if valid, False otherwise
    """
    pattern = re.compile(
        r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$|^([0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}$'
    )
    return bool(pattern.match(mac))


def validate_ip_address(ip: str) -> bool:
    """
    Validate IP address format.
    
    Args:
        ip: IP address string
        
    Returns:
        True if valid, False otherwise
    """
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def validate_command(command: str, allowed_commands: Optional[list] = None) -> bool:
    """
    Validate command for security.
    
    Args:
        command: Command string
        allowed_commands: List of allowed commands (whitelist mode)
        
    Returns:
        True if safe, False otherwise
    """
    # Block dangerous commands
    dangerous_patterns = [
        r'rm\s+-rf',
        r'format\s+',
        r'del\s+/[qf]',
        r'rmdir',
        r'powershell.*-enc',
        r'cmd\.exe.*/c',
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False
    
    # If whitelist is provided, check against it
    if allowed_commands:
        return command.strip().lower() in [c.lower() for c in allowed_commands]
    
    return True


def sanitize_mac_address(mac: str) -> str:
    """
    Normalize MAC address to standard format (XX:XX:XX:XX:XX:XX).
    
    Args:
        mac: MAC address string
        
    Returns:
        Normalized MAC address
    """
    # Remove common separators
    mac = mac.replace('-', '').replace('.', '').upper()
    
    # Add colons
    return ':'.join(mac[i:i+2] for i in range(0, 12, 2))
