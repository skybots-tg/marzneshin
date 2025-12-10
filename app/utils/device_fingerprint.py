"""Device fingerprinting utilities"""
import hashlib
from typing import Optional


def build_device_fingerprint(
    user_id: int,
    client_name: Optional[str] = None,
    tls_fingerprint: Optional[str] = None,
    os_guess: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[str, int]:
    """
    Build a device fingerprint from various identifiers.
    
    Args:
        user_id: User ID
        client_name: Client application name (v2rayNG, sing-box, etc.)
        tls_fingerprint: TLS fingerprint if available
        os_guess: Operating system guess
        user_agent: User agent string
    
    Returns:
        Tuple of (fingerprint_hash, version)
    """
    version = 1
    
    # Build source string from available identifiers
    components = [
        str(user_id),
        client_name or "",
        tls_fingerprint or "",
        os_guess or "",
        user_agent or "",
    ]
    
    source = "|".join(components)
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    
    return fingerprint, version


def guess_client_type(
    client_name: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """
    Guess client type from client name or user agent.
    
    Returns:
        Client type: android, ios, windows, macos, linux, other
    """
    if not client_name and not user_agent:
        return "other"
    
    identifier = f"{client_name or ''} {user_agent or ''}".lower()
    
    # Android clients
    if any(x in identifier for x in ["android", "v2rayng", "matsuri", "sagernet"]):
        return "android"
    
    # iOS clients
    if any(x in identifier for x in ["ios", "iphone", "ipad", "shadowrocket", "quantumult"]):
        return "ios"
    
    # Windows clients
    if any(x in identifier for x in ["windows", "v2rayn", "clash for windows", "clash-for-windows"]):
        return "windows"
    
    # macOS clients
    if any(x in identifier for x in ["macos", "darwin", "clashx"]):
        return "macos"
    
    # Linux clients
    if any(x in identifier for x in ["linux", "ubuntu", "debian"]):
        return "linux"
    
    return "other"


def extract_client_name(user_agent: Optional[str] = None) -> Optional[str]:
    """
    Try to extract client name from user agent.
    
    Common patterns:
    - v2rayNG/1.8.5
    - clash-meta/1.15.0
    - sing-box/1.5.0
    """
    if not user_agent:
        return None
    
    # Try to extract from common patterns
    parts = user_agent.split("/")
    if len(parts) >= 2:
        client = parts[0].strip()
        if client:
            return client
    
    # Try to extract from space-separated
    parts = user_agent.split()
    if parts:
        client = parts[0].strip()
        if client:
            return client
    
    return None


def normalize_client_name(client_name: Optional[str]) -> Optional[str]:
    """
    Normalize client name for consistency.
    """
    if not client_name:
        return None
    
    name = client_name.lower().strip()
    
    # Normalize common variations
    normalization_map = {
        "v2rayng": "v2rayNG",
        "v2rayn": "v2rayN",
        "clashx": "ClashX",
        "clash for windows": "Clash for Windows",
        "clash-for-windows": "Clash for Windows",
        "shadowrocket": "Shadowrocket",
        "quantumult": "Quantumult",
        "sing-box": "sing-box",
        "matsuri": "Matsuri",
        "sagernet": "SagerNet",
        "nekobox": "NekoBox",
    }
    
    return normalization_map.get(name, client_name)

