import time
import ujson
import machine
from ssd1322 import Display
from palettes import PALETTES

# --------------------------------------------------------------------------
# 1. MODULE STATE & CONFIGURATION
# --------------------------------------------------------------------------

# --- State Variables ---
_running = False
_screen = None
_menu_stack = [("root", 0)]
_device_presets = {}
_all_known_devices = set()
_is_sleeping = False
_last_activity_time = 0
_last_pot_value = 0

# --- Constants ---
SLEEP_TIMEOUT_MS = 15000

# --- Hardware Objects ---
_left_btn, _right_btn, _pot, _spi = None, None, None, None

# --- Functions/Data from main.py ---
_mesh_send = lambda msg: None
_get_device_id = lambda: "N/A"
_get_current_preset = lambda: "N/A"
# 🔹 FIXED: This will now hold the direct reference to main.py's list
_active_devices = {}

# --------------------------------------------------------------------------
# 2. SCRIPT API ("THE CONTRACT" with main.py)
# --------------------------------------------------------------------------

def init(params, mesh_send, get_device_id, get_current_preset, active_devices, **kwargs):
    """Initializes the script and returns event handlers."""
    global _running, _mesh_send, _get_device_id, _get_current_preset, _active_devices
    global _screen, _left_btn, _right_btn, _pot, _spi, _last_activity_time, _last_pot_value
    
    try:
        temp_spi = machine.SPI(params.get("spi_bus", 1), baudrate=8000000, 
                               sck=machine.Pin(params.get("sck")), 
                               mosi=machine.Pin(params.get("mosi")))
        temp_spi.deinit()
    except Exception:
        pass

    _mesh_send = mesh_send
    _get_device_id = get_device_id
    _get_current_preset = get_current_preset
    # 🔹 FIXED: Store the reference to main.py's authoritative list
    _active_devices = active_devices

    try:
        _left_btn = machine.Pin(params.get("left_btn", 1), machine.Pin.IN, machine.Pin.PULL_UP)
        _right_btn = machine.Pin(params.get("right_btn", 2), machine.Pin.IN, machine.Pin.PULL_UP)
        _pot = machine.ADC(machine.Pin(params.get("pot", 3)))
        _pot.atten(machine.ADC.ATTN_11DB)
        
        rst_pin = machine.Pin(params.get("rst"), machine.Pin.OUT)
        rst_pin.value(0); time.sleep_ms(50); rst_pin.value(1); time.sleep_ms(50)

        _spi = machine.SPI(params.get("spi_bus", 1), baudrate=8000000, 
                           sck=machine.Pin(params.get("sck")), 
                           mosi=machine.Pin(params.get("mosi")))
        
        cs_pin = machine.Pin(params.get("cs"), machine.Pin.OUT)
        dc_pin = machine.Pin(params.get("dc"), machine.Pin.OUT)
        _screen = Display(_spi, cs_pin, dc_pin, rst_pin)
        
        _last_activity_time = time.ticks_ms()
        _last_pot_value = _pot.read()
        _running = True
        print("[Interface] Initialized successfully.")
    except Exception as e:
        print(f"[Interface] ERROR: Hardware initialization failed: {e}")
        _running = False

    return {"on_heartbeat": _handle_heartbeat}

def run():
    """Main loop called by main.py."""
    global _is_sleeping, _last_activity_time, _last_pot_value
    if not _running: return
    
    # 🔹 REMOVED: Pruning logic is no longer needed as main.py handles it.
    
    activity_detected = False
    pot_val = _pot.read()
    
    if not _left_btn.value() or not _right_btn.value():
        activity_detected = True
    
    if pot_val is not None and abs(pot_val - _last_pot_value) > 50:
        activity_detected = True
        _last_pot_value = pot_val

    if activity_detected:
        _last_activity_time = time.ticks_ms()
        if _is_sleeping:
            _is_sleeping = False
            _draw_screen()
            time.sleep_ms(200)
            return

    if not _is_sleeping and time.ticks_diff(time.ticks_ms(), _last_activity_time) > SLEEP_TIMEOUT_MS:
        _is_sleeping = True

    if not _is_sleeping:
        if not _left_btn.value(): _move_left(); time.sleep_ms(200)
        if not _right_btn.value(): _move_right(); time.sleep_ms(200)

        menu = _get_menu_for_key(_get_current_menu_key())
        item_count = len(menu)
        if item_count > 0:
            new_index = int((_last_pot_value / 4095) * (item_count - 1) + 0.5)
            if new_index != _get_selected_index():
                _set_selected_index(new_index)
    
    _draw_screen()
    time.sleep_ms(30)


def stop():
    """Gracefully cleans up all resources used by the script."""
    global _running, _screen, _spi, _left_btn, _right_btn, _pot
    _running = False
    
    if _screen:
        try: _screen.cleanup()
        except Exception: pass
    
    if _spi:
        try: _spi.deinit()
        except Exception: pass

    _screen, _spi, _left_btn, _right_btn, _pot = None, None, None, None, None
    print("[Interface] Stopped and resources released.")

# --------------------------------------------------------------------------
# 3. EVENT HANDLERS & ACTIONS
# --------------------------------------------------------------------------
def _handle_heartbeat(msg):
    """Processes heartbeats to update device lists."""
    device_name = msg.get("device_name")
    if device_name:
        # The interface only needs to care about the historical list and presets.
        # main.py will handle timing out devices from the active list.
        _all_known_devices.add(device_name)
        presets = msg.get("all_presets")
        if presets is not None:
            _device_presets[device_name] = presets

def _execute_action(action_data):
    action_type, payload = action_data[0], action_data[1]
    msg = None
    if action_type == "send_preset":
        target_device, preset_name = payload
        msg = {"type": "preset", "target": target_device, "preset": preset_name}
    elif action_type == "send_palette":
        palette_name = payload
        palette_data = PALETTES.get(palette_name)
        if palette_data:
            msg = {"type": "palette"}
            msg.update(palette_data)
    if msg:
        json_msg = ujson.dumps(msg)
        _mesh_send(json_msg)
        print(f"[Interface DEBUG] Sent message: {json_msg}")
        _blink_confirmation()

# --------------------------------------------------------------------------
# 4. UI DRAWING & LAYOUT
# --------------------------------------------------------------------------

def _blink_confirmation():
    if not _screen: return
    key, idx = _menu_stack[-1]
    if key == "Device Info": return
    menu = _get_menu_for_key(key)
    options = list(menu.keys())
    if not options or idx >= len(options): return
    mesh_width, menu_x_start = 100, 104
    center_y = 15 + ((_screen.height - 20) // 2) - 4
    selected_text = options[idx]
    x, y = menu_x_start + 5, center_y
    text_width = len(selected_text) * 8
    _screen.gs4_fb.fill_rect(x - 2, y - 1, text_width + 4, 9, 15)
    _screen.gs4_fb.text(selected_text, x, y, 0)
    _screen.present()
    time.sleep_ms(150)

def _draw_screen():
    if not _screen: return
    _screen.gs4_fb.fill(0)

    if _is_sleeping:
        text = "LIGHTWEAVE MK1"
        text_width = len(text) * 8
        x = (_screen.width - text_width) // 2
        y = (_screen.height - 8) // 2
        _screen.gs4_fb.text(text, x, y, 2)
    else:
        mesh_width, menu_x_start, divider_x = 100, 104, 101
        _draw_mesh_column(0, mesh_width)
        _draw_menu_column(menu_x_start, _screen.width - menu_x_start)
        _screen.gs4_fb.vline(divider_x, 0, _screen.height, 10)

    _screen.present()

def _draw_mesh_column(x, width):
    _screen.gs4_fb.text("Mesh", x, 0, 15)
    _screen.gs4_fb.hline(x, 10, width, 15)
    
    own_id = _get_device_id()
    if own_id != "N/A":
        _all_known_devices.add(own_id)

    sorted_devices = sorted(list(_all_known_devices))
    if not sorted_devices:
        _screen.gs4_fb.text("Scanning...", x + 5, 25, 8)
        return
        
    for i, device_id in enumerate(sorted_devices):
        # 🔹 FIXED: Check against the live list from main.py and always show self as active.
        is_active = (device_id in _active_devices) or (device_id == own_id)
        
        text_color = 3 if is_active else 1
        _screen.gs4_fb.text(device_id, x + 4, 15 + i * 10, text_color)

def _draw_menu_column(x, width):
    key = _get_current_menu_key()
    if key == "Device Info":
        _screen.gs4_fb.text("Device Info", x, 0, 15)
        _screen.gs4_fb.hline(x, 10, width, 15)
        _screen.gs4_fb.text(f"ID: {_get_device_id()}", x + 2, 15, 15)
        _screen.gs4_fb.text(f"Preset:", x + 2, 25, 15)
        _screen.gs4_fb.text(f"{_get_current_preset()}", x+4, 35, 12)
    else:
        menu = _get_menu_for_key(key)
        options = list(menu.keys())
        idx = _get_selected_index()
        title = "Menu" if key == "root" else key
        _screen.gs4_fb.text(title, x, 0, 15)
        _screen.gs4_fb.hline(x, 10, width, 15)
        if not options:
            _screen.gs4_fb.text("...empty...", x + 5, 30, 8)
            return
        
        line_height = 10
        center_y = 15 + ((_screen.height - 20) // 2) - 4
        _screen.gs4_fb.text(f"{options[idx]}", x + 5, center_y, 15)

        if idx > 0: _screen.gs4_fb.text(f"{options[idx - 1]}", x + 5, center_y - line_height, 2)
        if idx > 1: _screen.gs4_fb.text(f"{options[idx - 2]}", x + 5, center_y - (line_height * 2), 3)
        if idx < len(options) - 1: _screen.gs4_fb.text(f"{options[idx + 1]}", x + 5, center_y + line_height, 2)
        if idx < len(options) - 2: _screen.gs4_fb.text(f"{options[idx + 2]}", x + 5, center_y + (line_height * 2), 3)

# --------------------------------------------------------------------------
# 5. INTERNAL HELPERS
# --------------------------------------------------------------------------
def _get_current_menu_key(): return _menu_stack[-1][0]
def _get_selected_index(): return _menu_stack[-1][1]
def _set_selected_index(idx): _menu_stack[-1] = (_get_current_menu_key(), idx)

def _move_left():
    if len(_menu_stack) > 1: _menu_stack.pop()

def _move_right():
    key, idx = _menu_stack[-1]
    menu = _get_menu_for_key(key)
    options = list(menu.keys())
    if not options or idx >= len(options): return
    selected_option = options[idx]
    if "action" in menu[selected_option]:
        _execute_action(menu[selected_option]["action"])
    else:
        _menu_stack.append((selected_option, 0))

def _get_menu_for_key(key):
    if key == "root":
        return {"Device Info": {}, "Commands": {}, "Palettes": {}}
    if key == "Commands":
        return {device: {} for device in sorted(_device_presets.keys())}
    if key in _device_presets:
        presets = _device_presets[key]
        return {p: {"action": ("send_preset", (key, p))} for p in sorted(presets)}
    if key == "Palettes":
        return {p_name: {"action": ("send_palette", p_name)} for p_name in sorted(PALETTES.keys())}
    return {}

