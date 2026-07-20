import network
import espnow as system_espnow

_e = None
BROADCAST_MAC = b'\xff' * 6  # ff:ff:ff:ff:ff:ff

def init():
    """Initialize WiFi (station mode) and ESP-NOW broadcast."""
    global _e
    sta = network.WLAN(network.STA_IF)
    # 🔹 FIXED: Ensure the interface is inactive before trying to configure it.
    sta.active(False)

    # Configure the channel and disable power saving BEFORE activating the radio.
    # This prevents race conditions and initialization errors.
    channel = 1
    print(f"[Mesh INFO] Set WiFi channel to {channel} and disabled power saving.")

    # Now, activate the WiFi station.
    sta.active(True)

    _e = system_espnow.ESPNow()
    _e.active(True)

    # Add broadcast peer
    try:
        _e.add_peer(BROADCAST_MAC)
    except OSError:
        # peer may already exist
        pass

    return _e

def send(msg: str):
    """Broadcast a UTF-8 message to all peers."""
    global _e
    if _e is None:
        raise RuntimeError("ESP-NOW not initialized, call init() first")
    
    print(f"[Mesh DEBUG] Sending: {msg}")
    
    _e.send(BROADCAST_MAC, msg.encode())

def recv():
    """Receive a message. Returns (mac, msg_str) or (None, None)."""
    global _e
    if _e is None:
        raise RuntimeError("ESP-NOW not initialized, call init() first")
        
    if _e.any():
        mac, msg_bytes = _e.recv()
        if msg_bytes:
            print(f"[Mesh DEBUG] Received raw: {msg_bytes} from {mac}")
            try:
                return mac, msg_bytes.decode()
            except UnicodeDecodeError:
                return mac, None
                
    return None, None

