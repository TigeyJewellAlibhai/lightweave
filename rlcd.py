"""MicroPython driver for the Waveshare ST7305 reflective LCD (RLCD).

Targets the 300x400 portrait panel on the Waveshare ESP32-S3-RLCD-4.2 board.
It is a 1-bit (black/white) reflective, e-paper-like display: no backlight,
low power, and a comparatively slow full-panel refresh.

The init sequence, addressing and pixel-packing scheme below are ported
directly from Waveshare's official ESP-IDF `display_bsp.cpp` driver for this
board, so they match known-working values rather than guessed ones.

Drawing is done through a normal `framebuf.FrameBuffer` (`self.fb`), so all
the usual methods are available: text(), pixel(), line(), rect(),
fill_rect(), hline(), vline(), etc. Call `present()` to push the buffer to
the panel - this repacks the framebuffer into the panel's native 4-wide x
2-tall pixel block layout and is the slow part, so avoid calling it more
often than necessary (this is a slow-refresh display, not a fast OLED).
"""
from framebuf import FrameBuffer, MONO_HLSB
from utime import sleep_ms

BLACK = 1
WHITE = 0


class Display:
    """Driver for the ST7305 RLCD panel.

    Args:
        spi (machine.SPI): SPI bus for the display.
        cs (machine.Pin): Chip select pin.
        dc (machine.Pin): Data/command pin.
        rst (machine.Pin): Reset pin.
        width (int): Panel width in pixels (default 300).
        height (int): Panel height in pixels (default 400).
    """

    def __init__(self, spi, cs, dc, rst, width=300, height=400):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.width = width
        self.height = height

        self.cs.init(self.cs.OUT, value=1)
        self.dc.init(self.dc.OUT, value=0)
        self.rst.init(self.rst.OUT, value=1)

        # Standard framebuffer used for all drawing.
        self._row_bytes = (width + 7) // 8
        self.buf = bytearray(self._row_bytes * height)
        self.fb = FrameBuffer(self.buf, width, height, MONO_HLSB)

        # Panel-native packed buffer (4px-wide x 2px-tall block per byte).
        self._panel_len = (width * height) // 8

        self.reset()
        self._init_panel()
        self.clear()

    # ------------------------------------------------------------------
    # Low level SPI helpers
    # ------------------------------------------------------------------
    def write_cmd(self, cmd, *data):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([cmd]))
        self.cs.value(1)
        if data:
            self.dc.value(1)
            self.cs.value(0)
            self.spi.write(bytes(data))
            self.cs.value(1)

    def reset(self):
        self.rst.value(1)
        sleep_ms(50)
        self.rst.value(0)
        sleep_ms(20)
        self.rst.value(1)
        sleep_ms(50)

    def _init_panel(self):
        wc = self.write_cmd
        wc(0xD6, 0x17, 0x02)   # NVM Load Control
        wc(0xD1, 0x01)         # Booster Enable
        wc(0xC0, 0x11, 0x04)   # Gate Voltage Control
        wc(0xC1, 0x69, 0x69, 0x69, 0x69)  # VSHP Setting
        wc(0xC2, 0x19, 0x19, 0x19, 0x19)  # VSLP Setting
        wc(0xC4, 0x4B, 0x4B, 0x4B, 0x4B)  # VSHN Setting
        wc(0xC5, 0x19, 0x19, 0x19, 0x19)  # VSLN Setting
        wc(0xD8, 0x80, 0xE9)
        wc(0xB2, 0x02)
        wc(0xB3, 0xE5, 0xF6, 0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45)
        wc(0xB4, 0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45)
        wc(0x62, 0x32, 0x03, 0x1F)
        wc(0xB7, 0x13)
        wc(0xB0, 0x64)
        wc(0x11)               # Sleep out
        sleep_ms(200)
        wc(0xC9, 0x00)
        wc(0x36, 0x48)         # MADCTL - memory access / orientation
        wc(0x3A, 0x11)         # Pixel format
        wc(0xB9, 0x20)
        wc(0xB8, 0x29)
        wc(0x21)               # Display inversion on (panel is normally-white)
        wc(0x2A, 0x12, 0x2A)   # Column address set
        wc(0x2B, 0x00, 0xC7)   # Row address set
        wc(0x35, 0x00)         # Tearing effect line on
        wc(0xD0, 0xFF)
        wc(0x38)                # Idle mode off
        wc(0x29)                # Display on

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def clear(self):
        self.fb.fill(WHITE)
        self.present()

    def present(self):
        """Repack the framebuffer into the panel's native layout and send it.

        This walks every pixel, so it is relatively slow (expect it to take
        noticeably longer than an OLED/TFT refresh). Only call this when the
        screen content has actually changed.
        """
        w, h = self.width, self.height
        row_bytes = self._row_bytes
        w4 = w // 4
        panel_buf = bytearray(self._panel_len)

        for y in range(h):
            byte_y = y >> 1
            local_y = y & 1
            row_off = y * row_bytes
            for x in range(w):
                if self.buf[row_off + (x >> 3)] & (0x80 >> (x & 7)):
                    byte_x = x >> 2
                    local_x = x & 3
                    idx = byte_y * w4 + byte_x
                    bit = 7 - (local_x * 2 + local_y)
                    panel_buf[idx] |= (1 << bit)

        self.write_cmd(0x2A, 0x12, 0x2A)
        self.write_cmd(0x2B, 0x00, 0xC7)
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([0x2C]))
        self.cs.value(1)
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(panel_buf)
        self.cs.value(1)

    def cleanup(self):
        """Clear the panel and release the SPI bus."""
        self.clear()
        try:
            self.spi.deinit()
        except Exception:
            pass
