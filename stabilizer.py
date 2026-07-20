from math import atan2, sqrt, degrees

# --------------------------------------------------------------------------
# 1. MODULE STATE
# --------------------------------------------------------------------------

# --- Hardware & Configuration References ---
_servo_l = None
_servo_r = None
_accel = None
_params = {}
_running = False

# --------------------------------------------------------------------------
# 2. SCRIPT API ("THE CONTRACT" with main.py)
# --------------------------------------------------------------------------

def init(params, servos, accel, **kwargs):
    """
    Initializes the script. Accepts a 'resource bundle' as keyword arguments.
    This script doesn't need to listen for events, so it returns None.
    """
    global _servo_l, _servo_r, _accel, _params, _running
    
    # Store references to the resources provided by main.py
    _params = params
    _accel = accel
    
    if not _accel:
        print("[stabilizer] WARN: Accelerometer not provided. Script will not run.")
        return None

    # Get servo IDs from the JSON params and find them in the servos dictionary
    servo_l_id = _params.get("servo_l")
    servo_r_id = _params.get("servo_r")

    if servo_l_id and servo_l_id in servos:
        _servo_l = servos[servo_l_id]
    else:
        print(f"[stabilizer] WARN: Left servo '{servo_l_id}' not found.")

    if servo_r_id and servo_r_id in servos:
        _servo_r = servos[servo_r_id]
    else:
        print(f"[stabilizer] WARN: Right servo '{servo_r_id}' not found.")
        
    # The script will only run if all required components are successfully found
    _running = _servo_l and _servo_r and _accel is not None
    if _running:
        print("[stabilizer] Initialized successfully.")
    else:
        print("[stabilizer] Initialization failed due to missing components.")
        
    return None # This script does not need to handle any events

def run():
    """The main loop for this script, called repeatedly by main.py."""
    global _running
    if not _running:
        return

    try:
        # 🔹 FIXED: Reverted to the correct function name from the original working script.
        ax, ay, az = _accel.read_accel_data()

        # Calculate tilt angles using the original formula
        pitch = atan2(-ax, sqrt(ay**2 + az**2))
        roll  = atan2(ay, sqrt(ax**2 + az**2))

        # Convert to degrees and apply scaling factors
        pitch_deg = degrees(pitch) * _params.get("pitch_scale", 1.0)
        roll_deg = degrees(roll) * _params.get("roll_scale", 1.0)

        # Calculate differential servo angles
        base = _params.get("base_angle", 90)
        l_angle = base + pitch_deg + roll_deg
        r_angle = base + pitch_deg - roll_deg

        # Clamp angles to their configured limits
        min_a = _params.get("min_angle", 0)
        max_a = _params.get("max_angle", 180)
        l_angle = max(min_a, min(max_a, l_angle))
        r_angle = max(min_a, min(max_a, r_angle))

        # Enforce max difference to prevent mechanical strain
        max_diff = _params.get("max_diff", 180)
        diff = l_angle - r_angle
        if abs(diff) > max_diff:
            if diff > 0:
                r_angle = l_angle - max_diff
            else:
                l_angle = r_angle - max_diff
            
        # Write to servos, inverting the left servo for mirrored mounting
        _servo_l.write_angle(int(180 - l_angle))
        _servo_r.write_angle(int(r_angle))

    except Exception as e:
        print(f"[stabilizer] run error: {e}")
        _running = False # Stop running on error to prevent log spam

def stop():
    """Cleans up when the script is stopped."""
    global _running
    _running = False
    print("[stabilizer] stopped")

