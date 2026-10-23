import machine
import neopixel
import time
import random

# 1. Drive Pin 4 HIGH

NUM_LEDS = 8
pin3 = machine.Pin(3, machine.Pin.OUT)
np = neopixel.NeoPixel(pin3, NUM_LEDS, bpp=4)

pin4 = machine.Pin(4, machine.Pin.OUT)


# 2. Setup SK6812 (RGBW) NeoPixel on Pin 3 (8 LEDs, bpp=4)


def fire_flicker():
    while True:
        for i in range(NUM_LEDS):
            # Red channel for core flame warmth
            r = random.randint(180, 255)
            # Green channel for orange/yellow highlights
            g = random.randint(15, 60)
            # Blue channel (keep zero for a warm tone)
            b = 0
            # Dedicated White channel for subtle bright embers/hotspots
            w = random.randint(0, 15)
            
            np[i] = (r, g, b, w)
        
        np.write()
        # Randomize timing for dynamic flicker
        time.sleep_ms(random.randint(40, 120))

        pin4.value(1)

# Run animation
try:
    fire_flicker()
except KeyboardInterrupt:
    # Clear pixels on stop (4 channels)
    np.fill((0, 0, 0, 0))
    np.write()