import time
import ujson
import machine
import os
import servo
import mesh
from led_controller import LedController

# --------------------------------------------------------------------------
# 1. INITIAL SETUP
# --------------------------------------------------------------------------

json_file = next((f for f in os.listdir() if f.endswith(".json")))
if not json_file:
    raise RuntimeError("No JSON config file found!")

print(f"[INFO] Using config file: {json_file}")
with open(json_file) as f:
    config = ujson.load(f)

# --- Global State & Constants ---
DEVICE_ID = config["device"]["id"]
DEBUG = config["device"].get("debug", False)
HEARTBEAT_INTERVAL_MS = 60000

# --- Hardware & Script Objects ---
servos, leds, buttons, accel = {}, {}, {}, None
active_scripts, background_scripts = [], []
active_devices = {}
_servo_tasks = [] # 🔹 NEW: A list to manage non-blocking servo movements

# --- State Variables ---
_current_palette = None
_current_preset = None
_last_heartbeat = 0

# --- Event System for Modular Scripts ---
_bg_event_handlers = {"on_heartbeat": []}
_reg_event_handlers = {"on_heartbeat": []}

# --------------------------------------------------------------------------
# 2. CORE LOGIC (PALETTES, PRESETS, & SERVO MANAGER)
# --------------------------------------------------------------------------

def get_palette():
    """Returns the current global palette dictionary."""
    return _current_palette

def apply_palette(palette_data):
    """Sets the active global palette and updates all LED strips."""
    global _current_palette
    if not palette_data: return
    
    valid_keys = ["primary", "secondary", "tertiary", "pulse", "variance"]
    clean_palette = {key: palette_data[key] for key in valid_keys if key in palette_data}

    if not clean_palette: return

    _current_palette = clean_palette
    for strip in leds.values():
        strip.set_palette(**clean_palette)
        
    if DEBUG: print(f"[DEBUG] Applied global palette: {clean_palette}")

def apply_preset(preset_id):
    """
    🔹 REFACTORED: This function is now NON-BLOCKING.
    It applies immediate changes (LEDs, scripts) and creates a background
    task for the time-based servo movements.
    """
    global _current_preset, _servo_tasks
    stop_scripts()

    if _current_preset != preset_id:
        _current_preset = preset_id
        send_heartbeat(force=True)

    preset = config["device"].get("presets", {}).get(preset_id)
    if not preset:
        if DEBUG: print(f"[DEBUG] Preset '{preset_id}' not found")
        return

    if DEBUG: print(f"[DEBUG] Applying preset '{preset_id}'")
    
    # --- IMMEDIATE ACTIONS ---
    # 1. Apply LED settings instantly.
    for led_id, settings in preset.get("leds", {}).items():
        if led_id in leds:
            leds[led_id].set_animation(settings.get("animation"))
            palette = settings.get("palette") or _current_palette
            if palette:
                leds[led_id].set_palette(**palette)

    # --- BACKGROUND SERVO TASK ---
    # 2. Collect all servo moves and create a single task for the manager.
    servo_moves = []
    for servo_id, entry in preset.get("servos", {}).items():
        if servo_id in servos:
            angle = entry.get("angle", 90) if isinstance(entry, dict) else entry
            delay = entry.get("delay", 0) if isinstance(entry, dict) else 0
            servo_moves.append((delay, servo_id, angle))
    
    if servo_moves:
        servo_moves.sort(key=lambda x: x[0])
        new_task = {
            "start_time": time.ticks_ms(),
            "moves": servo_moves,
            "moved_servos": [],
            "state": "moving"  # Initial state
        }
        _servo_tasks.append(new_task)
        if DEBUG: print(f"[Servo Manager] Created task with {len(servo_moves)} moves.")

    # --- IMMEDIATE ACTIONS (Continued) ---
    # 3. Start any associated scripts immediately.
    if "scripts" in preset:
        start_scripts(preset["scripts"])

def _update_servos():
    """
    🔹 NEW: The non-blocking Servo Manager.
    This is called in every main loop iteration to process servo tasks.
    """
    global _servo_tasks
    if not _servo_tasks: return
    
    now = time.ticks_ms()
    # Iterate over a copy of the list to allow safe removal of finished tasks
    for task in _servo_tasks[:]:
        if task["state"] == "moving":
            remaining_moves = []
            for move in task["moves"]:
                delay_ms, sid, angle = move[0] * 1000, move[1], move[2]
                if time.ticks_diff(now, task["start_time"]) >= delay_ms:
                    servos[sid].write_angle(angle)
                    if servos[sid] not in task["moved_servos"]:
                        task["moved_servos"].append(servos[sid])
                else:
                    remaining_moves.append(move)
            task["moves"] = remaining_moves

            # If all moves for this task are done, switch to the 'settling' state
            if not task["moves"]:
                task["state"] = "settling"
                task["settle_start_time"] = now
                if DEBUG: print("[Servo Manager] Moves complete, settling...")

        elif task["state"] == "settling":
            # Wait for the settling period (2 seconds) to finish
            if time.ticks_diff(now, task["settle_start_time"]) >= 2000:
                for s in task["moved_servos"]:
                    s.deinit()
                if DEBUG: print(f"[Servo Manager] Settle complete, de-init {len(task['moved_servos'])} servos.")
                _servo_tasks.remove(task)

# --------------------------------------------------------------------------
# 3. MODULAR SCRIPT MANAGEMENT (Unchanged)
# --------------------------------------------------------------------------
def _start_script_group(scripts_cfg, script_list, script_type, event_handlers):
    if script_type == "regular": stop_scripts()
    elif script_type == "background": stop_background_scripts()
    resources = {
        "servos": servos, "leds": leds, "accel": accel,
        "active_devices": active_devices, "mesh_send": mesh.send,
        "get_device_id": lambda: DEVICE_ID,
        "get_current_preset": lambda: _current_preset,
        "local_presets": list(config["device"].get("presets", {}).keys()),
        "apply_preset": apply_preset,
        "apply_palette": apply_palette,
        "get_palette": get_palette  # 🔹 ADD THIS LINE
    }
    for s_cfg in scripts_cfg:
        try:
            mod = __import__(s_cfg["module"])
            resources["params"] = s_cfg.get("params", {})
            handlers = mod.init(**resources)
            script_list.append(mod)
            if handlers:
                for event, handler in handlers.items():
                    if event in event_handlers: event_handlers[event].append(handler)
            if DEBUG: print(f"[DEBUG] Started {script_type} script: {s_cfg['module']}")
        except Exception as e:
            print(f"[WARN] Failed to start {s_cfg['module']}: {e}")

def _run_script_group(script_list):
    for mod in script_list:
        if hasattr(mod, "run"): mod.run()
def _stop_script_group(script_list, event_handlers):
    for mod in script_list:
        if hasattr(mod, "stop"): mod.stop()
    script_list.clear()
    for handlers in event_handlers.values():
        handlers.clear()

def start_scripts(cfg): _start_script_group(cfg, active_scripts, "regular", _reg_event_handlers)
def run_scripts(): _run_script_group(active_scripts)
def stop_scripts(): _stop_script_group(active_scripts, _reg_event_handlers)
def start_background_scripts(): _start_script_group(config["device"].get("background", []), background_scripts, "background", _bg_event_handlers)
def run_background_scripts(): _run_script_group(background_scripts)
def stop_background_scripts(): _stop_script_group(background_scripts, _bg_event_handlers)

# --------------------------------------------------------------------------
# 4. COMMUNICATION (Unchanged)
# --------------------------------------------------------------------------
def send_or_apply(msg):
    if not isinstance(msg, dict): return
    preset_id = msg.get("preset")
    if not preset_id: return
    target = msg.get("target", "all")
    if target == DEVICE_ID or target == "all":
        apply_preset(preset_id)
    if target != DEVICE_ID:
        if "type" not in msg: msg["type"] = "preset"
        mesh.send(ujson.dumps(msg))
        if DEBUG: print(f"[DEBUG] Broadcasted: {msg}")

def check_incoming():
    mac, msg_str = mesh.recv()
    if not msg_str: return
    try: data = ujson.loads(msg_str)
    except ValueError: return
    msg_type = data.get("type")
    if msg_type == "preset" and data.get("target") == DEVICE_ID:
        apply_preset(data.get("preset"))
    elif msg_type == "palette":
        apply_palette(data)
    elif msg_type == "heartbeat":
        active_devices[data["device_name"]] = {"last_heartbeat": time.ticks_ms()}
        for handler in _bg_event_handlers["on_heartbeat"]: handler(data)
        for handler in _reg_event_handlers["on_heartbeat"]: handler(data)
        if DEBUG: print(f"[DEBUG] Heartbeat from {data.get('device_name')}")

def check_buttons():
    for pin, b in buttons.items():
        val = b["pin"].value()
        cfg = b["config"]
        if b["last"] == 1 and val == 0:
            if "send" in cfg:
                for msg in cfg["send"]: send_or_apply(msg)
            elif "cycle" in cfg:
                idx = b["cycle_idx"]
                messages = cfg["cycle"][idx]
                for msg in messages: send_or_apply(msg)
                b["cycle_idx"] = (idx + 1) % len(cfg["cycle"])
            elif "press" in cfg:
                for msg in cfg["press"]: send_or_apply(msg)
        elif b["last"] == 0 and val == 1:
            if "release" in cfg:
                for msg in cfg["release"]: send_or_apply(msg)
        b["last"] = val

def send_heartbeat(force=False):
    global _last_heartbeat
    now = time.ticks_ms()
    if not force and time.ticks_diff(now, _last_heartbeat) < HEARTBEAT_INTERVAL_MS: return
    _last_heartbeat = now
    payload = {"type": "heartbeat", "device_name": DEVICE_ID, "active_preset": _current_preset, "all_presets": list(config["device"].get("presets", {}).keys())}
    mesh.send(ujson.dumps(payload))

# --------------------------------------------------------------------------
# 5. INITIALIZATION (Unchanged)
# --------------------------------------------------------------------------
for s_cfg in config["device"].get("servos", []): servos[s_cfg["id"]] = servo.Servo(s_cfg["pin"])
for l_cfg in config["device"].get("leds", []): leds[l_cfg["id"]] = LedController(l_cfg["pin"], l_cfg["count"])
for b_cfg in config["device"].get("buttons", []): buttons[b_cfg["pin"]] = {"pin": machine.Pin(b_cfg["pin"], machine.Pin.IN, machine.Pin.PULL_UP), "config": b_cfg, "last": 1, "cycle_idx": 0}
if "imu" in config["device"]:
    try:
        from imu import MPU6050
        i2c = machine.I2C(0, scl=machine.Pin(config["device"]["imu"]["scl"]), sda=machine.Pin(config["device"]["imu"]["sda"]))
        accel = MPU6050(i2c)
        accel.wake()
    except Exception as e: print(f"[WARN] Failed to init accelerometer: {e}")
mesh.init()
start_background_scripts()
if "palette" in config["device"]: apply_palette(config["device"]["palette"])
default_preset = config["device"].get("default_preset")
presets = config["device"].get("presets", {})
if default_preset and default_preset in presets: apply_preset(default_preset)
elif presets: apply_preset(list(presets.keys())[0])

# --------------------------------------------------------------------------
# 6. MAIN EXECUTION LOOP
# --------------------------------------------------------------------------
print(f"[INFO] Device {DEVICE_ID} ready.")
last_update = time.ticks_ms()
time.sleep_ms(500)

while True:
    check_buttons()
    check_incoming()
    _update_servos() # 🔹 ADDED: Call the servo manager in every loop
    
    now = time.ticks_ms()
    if time.ticks_diff(now, last_update) >= 150:
        run_background_scripts()
        run_scripts()
        for strip in leds.values():
            strip.update()
        last_update = now

    for dev_id in list(active_devices.keys()):
        if time.ticks_diff(now, active_devices[dev_id]["last_heartbeat"]) > HEARTBEAT_INTERVAL_MS + 20000:
            del active_devices[dev_id]

    send_heartbeat()
    time.sleep_ms(20)

