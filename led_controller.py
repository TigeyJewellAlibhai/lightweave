import time
import machine
import neopixel
import random

class LedController:
    def __init__(self, pin, count, name=None):
        self.name = name or f"LED_{pin}"
        self.np = neopixel.NeoPixel(machine.Pin(pin), count)
        self.count = count

        # Palette parameters
        self.primary = (255, 0, 0)
        self.secondary = (0, 255, 0)
        self.tertiary = (0, 0, 255)
        self.pulse = (255, 255, 255)

        self.brightness = 1.0  # 0..1
        self.variance = 0.0    # 0..1

        # Animation state
        self.animation = None
        self.last_update = time.ticks_ms()
        self.animation_params = {}

    # ---------------------------
    # Palette update
    # ---------------------------
    def set_palette(self, primary=None, secondary=None, tertiary=None,
                    pulse=None, variance=None):
        if primary: self.primary = primary
        if secondary: self.secondary = secondary
        if tertiary: self.tertiary = tertiary
        if pulse: self.pulse = pulse
        if variance is not None: self.variance = variance

    # ---------------------------
    # Animation control
    # ---------------------------
    def set_animation(self, anim_name, **params):
        self.animation = anim_name
        self.animation_params = params

    # ---------------------------
    # Helper: apply brightness and variance
    # ---------------------------
    def apply_color(self, color):
        r, g, b = color
        # Apply variance
        var_amount = int(255 * self.variance)
        r = max(0, min(255, int(r + random.randint(-var_amount, var_amount))))
        g = max(0, min(255, int(g + random.randint(-var_amount, var_amount))))
        b = max(0, min(255, int(b + random.randint(-var_amount, var_amount))))
        return (r, g, b)

    # ---------------------------
    # Animations
    # ---------------------------
    def animation_sparkle(self):
        # Random LEDs light up in primary color briefly
        for i in range(self.count):
            if random.random() < 0.1:  # 10% chance of sparkle
                self.np[i] = self.apply_color(self.primary)
            else:
                self.np[i] = (0, 0, 0)
        self.np.write()

    def animation_fire(self):
        # Fire: flicker between primary->secondary
        for i in range(self.count):
            base = self.primary if random.random() < 0.6 else self.secondary
            self.np[i] = self.apply_color(base)
        self.np.write()

    def animation_glow(self):
        # Glow: all LEDs fade in/out over time
        now = time.ticks_ms()
        t = (time.ticks_diff(now, self.last_update) / 1000.0)
        intensity = (1 + machine.math.sin(t*2)) / 2  # 0..1
        color = tuple(int(c * intensity) for c in self.primary)
        color = self.apply_color(color)
        for i in range(self.count):
            self.np[i] = color
        self.np.write()

    def animation_fill_primary(self):
        # 🔹 FIXED: Use the raw color without applying variance for a solid fill.
        color = self.primary
        for i in range(self.count):
            self.np[i] = color
        self.np.write()

    def animation_fill_secondary(self):
        # 🔹 FIXED: Use the raw color without applying variance for a solid fill.
        color = self.secondary
        for i in range(self.count):
            self.np[i] = color
        self.np.write()

    def animation_fill_tertiary(self):
        # 🔹 FIXED: Use the raw color without applying variance for a solid fill.
        color = self.tertiary
        for i in range(self.count):
            self.np[i] = color
        self.np.write()

    def animation_off(self):
        for i in range(self.count):
            self.np[i] = (0, 0, 0)
        self.np.write()

    def animation_pulse(self):
        color = self.apply_color(self.pulse)
        for i in range(self.count):
            self.np[i] = color
        self.np.write()

    # ---------------------------
    # Run current animation
    # ---------------------------
    def update(self):
        if not self.animation:
            return

        anim_func = getattr(self, f"animation_{self.animation}", None)
        if anim_func:
            anim_func()
