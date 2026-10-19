import time
import ujson
import machine
from rlcd import Display
from palettes import PALETTES

# --------------------------------------------------------------------------
# 1. MODULE STATE & CONFIGURATION
# --------------------------------------------------------------------------
#
# UI/menu structure is the same as interface.py (mesh device list + a
# root/Commands/Palettes/Device Info menu), adapted for the RLCD's
# monochrome 300x400 portrait panel and its two onboard buttons (BOOT and
# KEY) instead of the ssd1322 interface's left/right buttons + potentiometer.
#
# Because the RLCD is a slow-refresh reflective panel (like e-paper), the
# screen is only redrawn when something actually changes, rather than every
# loop tick.

# --- State Variables ---
_running = False
_screen = None
_menu_stack = [("root", 0)]
_device_presets = {}
_all_known_devices = set()
_is_sleeping = False
_last_activity_time = 0
_dirty = True

# --- Constants ---
SLEEP_TIMEOUT_MS = 30000
LONG_PRESS_MS = 600

# --- Hardware Objects ---
_boot_btn, _key_btn = None, None
_boot_last, _key_last = 1, 1
_key_press_start = 0
_key_long_fired = False

# --- Functions/Data from main.py ---
_mesh_send = lambda msg: None
_get_device_id = lambda: "N/A"
_get_current_preset = lambda: "N/A"
_active_devices = {}

# --------------------------------------------------------------------------
# 2. SCRIPT API ("THE CONTRACT" with main.py)
# --------------------------------------------------------------------------

def init(params, mesh_send, get_device_id, get_current_preset, active_devices, **kwargs):
    """Initializes the script and returns event handlers."""
    global _running, _mesh_send, _get_device_id, _get_current_preset, _active_devices
    global _screen, _boot_btn, _key_btn, _last_activity_time

    _mesh_send = mesh_send
    _get_device_id = get_device_id
    _get_current_preset = get_current_preset
    _active_devices = active_devices

    try:
        _boot_btn = machine.Pin(params.get("boot_btn", 0), machine.Pin.IN, machine.Pin.PULL_UP)
        _key_btn = machine.Pin(params.get("key_btn", 18), machine.Pin.IN, machine.Pin.PULL_UP)

        rst_pin = machine.Pin(params.get("rst", 41), machine.Pin.OUT)
        rst_pin.value(1)

        spi = machine.SPI(params.get("spi_bus", 1), baudrate=params.get("baudrate", 10000000),
                          sck=machine.Pin(params.get("sck", 11)),
                          mosi=machine.Pin(params.get("mosi", 12)))

        cs_pin = machine.Pin(params.get("cs", 40), machine.Pin.OUT)
        dc_pin = machine.Pin(params.get("dc", 5), machine.Pin.OUT)
        _screen = Display(spi, cs_pin, dc_pin, rst_pin,
                          width=params.get("width", 300), height=params.get("height", 400))

        _last_activity_time = time.ticks_ms()
        _running = True
        print("[RLCD Interface] Initialized successfully.")
    except Exception as e:
        print(f"[RLCD Interface] ERROR: Hardware initialization failed: {e}")
        _running = False

    return {"on_heartbeat": _handle_heartbeat}

def run():
    """Main loop called by main.py."""
    global _is_sleeping, _last_activity_time, _dirty
    global _boot_last, _key_last, _key_press_start, _key_long_fired
    if not _running:
        return

    now = time.ticks_ms()
    boot_val = _boot_btn.value()
    key_val = _key_btn.value()
    activity = False

    # BOOT: short press = back / up a menu level
    if _boot_last == 1 and boot_val == 0:
        activity = True
        if not _is_sleeping:
            _move_back()
    _boot_last = boot_val

    # KEY: short press = next item, long press (held) = select
    if _key_last == 1 and key_val == 0:
        activity = True
        _key_press_start = now
        _key_long_fired = False
    elif _key_last == 0 and key_val == 0 and not _key_long_fired:
        if time.ticks_diff(now, _key_press_start) >= LONG_PRESS_MS:
            _key_long_fired = True
            if not _is_sleeping:
                _select()
    elif _key_last == 0 and key_val == 1:
        if not _key_long_fired and not _is_sleeping:
            _cycle_selection()
        _key_long_fired = False
    _key_last = key_val

    if activity:
        _last_activity_time = now
        if _is_sleeping:
            _is_sleeping = False
            _dirty = True

    if not _is_sleeping and time.ticks_diff(now, _last_activity_time) > SLEEP_TIMEOUT_MS:
        _is_sleeping = True
        _dirty = True

    if _dirty:
        _draw_screen()
        _dirty = False

    time.sleep_ms(30)

def stop():
    """Gracefully cleans up all resources used by the script."""
    global _running, _screen
    _running = False
    if _screen:
        try: _screen.cleanup()
        except Exception: pass
    _screen = None
    print("[RLCD Interface] Stopped and resources released.")

# --------------------------------------------------------------------------
# 3. EVENT HANDLERS & ACTIONS
# --------------------------------------------------------------------------
def _handle_heartbeat(msg):
    """Processes heartbeats to update device lists."""
    global _dirty
    device_name = msg.get("device_name")
    if device_name:
        _all_known_devices.add(device_name)
        presets = msg.get("all_presets")
        if presets is not None:
            _device_presets[device_name] = presets
        _dirty = True

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
        print(f"[RLCD Interface DEBUG] Sent message: {json_msg}")
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
    selected_text = options[idx]
    x, y = 10, 210
    text_width = len(selected_text) * 8
    _screen.fb.fill_rect(x - 2, y - 2, text_width + 4, 12, 1)
    _screen.fb.text(selected_text, x, y, 0)
    _screen.present()
    time.sleep_ms(200)

def _draw_screen():
    if not _screen: return
    _screen.fb.fill(0)

    if _is_sleeping:
        text = "LIGHTWEAVE"
        x = (_screen.width - len(text) * 8) // 2
        y = (_screen.height - 8) // 2
        _screen.fb.text(text, x, y, 1)
    else:
        _screen.fb.text("LIGHTWEAVE RLCD", 8, 6, 1)
        _screen.fb.hline(0, 18, _screen.width, 1)
        _draw_mesh_section(8, 26, 120)
        _screen.fb.hline(0, 152, _screen.width, 1)
        _draw_menu_section(8, 162)

    _screen.present()

def _draw_mesh_section(x, y, height):
    _screen.fb.text("Mesh", x, y, 1)
    y += 12
    own_id = _get_device_id()
    if own_id != "N/A":
        _all_known_devices.add(own_id)

    sorted_devices = sorted(list(_all_known_devices))
    if not sorted_devices:
        _screen.fb.text("Scanning...", x, y, 1)
        return

    max_rows = height // 14
    for i, device_id in enumerate(sorted_devices[:max_rows]):
        is_active = (device_id in _active_devices) or (device_id == own_id)
        label = ("* " if is_active else "  ") + device_id
        _screen.fb.text(label, x, y + i * 14, 1)

def _draw_menu_section(x, y):
    key = _get_current_menu_key()
    if key == "Device Info":
        _screen.fb.text("Device Info", x, y, 1)
        _screen.fb.text(f"ID: {_get_device_id()}", x, y + 16, 1)
        _screen.fb.text("Preset:", x, y + 32, 1)
        _screen.fb.text(f"{_get_current_preset()}", x, y + 48, 1)
        return

    menu = _get_menu_for_key(key)
    options = list(menu.keys())
    idx = _get_selected_index()
    title = "Menu" if key == "root" else key
    _screen.fb.text(title, x, y, 1)

    if not options:
        _screen.fb.text("...empty...", x, y + 20, 1)
        return

    line_height = 20
    center_y = y + 40
    for offset in range(-3, 4):
        opt_idx = idx + offset
        if opt_idx < 0 or opt_idx >= len(options):
            continue
        line_y = center_y + offset * line_height
        text = options[opt_idx]
        if offset == 0:
            _screen.fb.fill_rect(x - 2, line_y - 2, len(text) * 8 + 4, 12, 1)
            _screen.fb.text(text, x, line_y, 0)
        else:
            _screen.fb.text(text, x, line_y, 1)

# --------------------------------------------------------------------------
# 5. INTERNAL HELPERS / MENU NAVIGATION
# --------------------------------------------------------------------------
def _get_current_menu_key(): return _menu_stack[-1][0]
def _get_selected_index(): return _menu_stack[-1][1]
def _set_selected_index(idx): _menu_stack[-1] = (_get_current_menu_key(), idx)

def _cycle_selection():
    global _dirty
    key = _get_current_menu_key()
    menu = _get_menu_for_key(key)
    options = list(menu.keys())
    if not options: return
    idx = (_get_selected_index() + 1) % len(options)
    _set_selected_index(idx)
    _dirty = True

def _move_back():
    global _dirty
    if len(_menu_stack) > 1:
        _menu_stack.pop()
        _dirty = True

def _select():
    global _dirty
    key, idx = _menu_stack[-1]
    menu = _get_menu_for_key(key)
    options = list(menu.keys())
    if not options or idx >= len(options): return
    selected_option = options[idx]
    if "action" in menu[selected_option]:
        _execute_action(menu[selected_option]["action"])
    else:
        _menu_stack.append((selected_option, 0))
    _dirty = True

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
