import time
import random

# --------------------------------------------------------------------------
# 1. MODULE STATE
# --------------------------------------------------------------------------

_leds = {}
_servos = {}
_params = {}
_running = False
_next_event_time = 0
_get_palette = lambda: None # Placeholder for the function from main.py

# --------------------------------------------------------------------------
# 2. SCRIPT API ("THE CONTRACT" with main.py)
# --------------------------------------------------------------------------

def init(params, leds, servos, get_palette, **kwargs):
    """
    Initializes the script. Accepts the resource bundle from main.py.
    """
    global _leds, _servos, _params, _running, _get_palette
    
    _params = params
    _leds = leds
    _servos = servos
    _get_palette = get_palette # Store the get_palette function
    _running = True
    
    _schedule_next_event()
    print("[Ambiance] Initialized and running.")
    
    return None # This script does not need to handle any events

def run():
    """
    The main loop, called repeatedly by main.py.
    """
    if not _running:
        return

    if time.ticks_diff(time.ticks_ms(), _next_event_time) > 0:
        _trigger_event()
        _schedule_next_event()

def stop():
    """Cleans up when the script is stopped."""
    global _running
    _running = False
    print("[Ambiance] Stopped.")

# --------------------------------------------------------------------------
# 3. INTERNAL LOGIC
# --------------------------------------------------------------------------

def _schedule_next_event():
    """Calculates a new random delay for the next event."""
    global _next_event_time
    min_delay_m = _params.get("min_delay_minutes", 1)
    max_delay_m = _params.get("max_delay_minutes", 3)
    delay_ms = random.randint(int(min_delay_m * 60 * 1000), int(max_delay_m * 60 * 1000))
    _next_event_time = time.ticks_add(time.ticks_ms(), delay_ms)
    print(f"[Ambiance] Next event in {delay_ms / 1000} seconds.")

def _trigger_event():
    """Executes the defined ambient effects (LED blinks and servo twitches)."""
    print("[Ambiance] Triggering event...")
    
    # --- LED Blinking (Now uses the global palette) ---
    led_targets = _params.get("led_targets", [])
    if led_targets:
        num_blinks = _params.get("led_blinks", 3)
        
        current_palette = _get_palette()
        blink_color = [20, 20, 20] # Default fallback color

        if current_palette:
            color_key = _params.get("led_color_key", "primary")
            blink_color = current_palette.get(color_key, blink_color)

        target_strips = [strip for led_id, strip in _leds.items() if led_id in led_targets]
        
        # 🔹 FIXED: Access the .np attribute to call fill() and write()
        for _ in range(num_blinks):
            for strip in target_strips:
                strip.np.fill(blink_color)
                strip.np.write()
            time.sleep_ms(60)
            for strip in target_strips:
                strip.np.fill((0, 0, 0))
                strip.np.write()
            time.sleep_ms(100)

    # --- Servo Twitching ---
    servo_targets = _params.get("servo_targets", {})
    if servo_targets:
        for servo_id, twitch_info in servo_targets.items():
            if servo_id in _servos:
                s = _servos[servo_id]
                base_angle = twitch_info.get("base_angle", 90)
                twitch_amount = twitch_info.get("twitch_amount", 5)
                
                s.write_angle(base_angle + twitch_amount)
                time.sleep_ms(150)
                s.write_angle(base_angle)
                time.sleep_ms(300)
                s.deinit()

