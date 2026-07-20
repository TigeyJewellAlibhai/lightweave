# servo.py — MicroPython Servo helper with safe deinit
from machine import Pin, PWM
import time

class Servo:
    def __init__(self, pin, freq=50, min_us=500, max_us=2500, angle_range=180):
        if isinstance(pin, int):
            pin = Pin(pin, Pin.OUT)
        self._pin = pin
        self.freq = freq
        self.min_us = min_us
        self.max_us = max_us
        self.angle_range = angle_range
        self._last_angle = None
        self._init_pwm()

    def _init_pwm(self):
        self.pwm = PWM(self._pin, freq=self.freq)

    def enable(self):
        if not hasattr(self, "pwm") or self.pwm is None:
            self._init_pwm()

    def _angle_to_duty_u16(self, angle):
        if angle < 0:
            angle = 0
        elif angle > self.angle_range:
            angle = self.angle_range
        us = self.min_us + (self.max_us - self.min_us) * angle // self.angle_range
        return int(us * 65535 // (1000000 // self.freq))

    def write_angle(self, angle):
        self.enable()
        duty_u16 = self._angle_to_duty_u16(angle)
        self.pwm.duty_u16(duty_u16)
        self._last_angle = angle

    def deinit(self):
        # keep the last pulse for 50 ms to stabilize small servos
        if self.pwm is not None and self._last_angle is not None:
            duty_u16 = self._angle_to_duty_u16(self._last_angle)
            self.pwm.duty_u16(duty_u16)
            time.sleep_ms(50)

        # now deinit PWM
        if self.pwm:
            try:
                self.pwm.deinit()
            except Exception:
                pass
            self.pwm = None

        # force pin low (do NOT float)
        try:
            self._pin.init(Pin.OUT, value=0)
        except Exception:
            pass