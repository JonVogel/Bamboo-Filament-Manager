# -*- coding: utf-8 -*-

"""
Nelko P21 label printer driver using TSPL2 protocol over serial.

The Nelko P21 is a portable Bluetooth thermal label printer that accepts
TSPL2 text commands over a serial (RFCOMM / COM) connection at 115200 baud.

Specs:
  - Resolution: 203 DPI
  - Label size: 15mm x 40mm (P21 label), with 5mm gap
  - Print area: 96 x 284 pixels (1-bit monochrome)
  - Protocol: TSPL2 subset (CRLF-terminated text commands)
  - The printer receives portrait images (96 wide x 284 tall) and handles
    orientation internally. For landscape labels, create a 284x96 image
    and this driver rotates it before sending.

Reference: https://github.com/merlinschumacher/nelko-p21-print
"""

import time
from pathlib import Path

import serial
from PIL import Image


# Print area in pixels at 203 DPI (printer's native orientation: portrait)
PRINT_WIDTH_PX = 96
PRINT_HEIGHT_PX = 284

# Landscape canvas size (how labels are designed — wide x short)
LABEL_WIDTH_PX = 284
LABEL_HEIGHT_PX = 96

# Raw bitmap size: 96/8 * 284 = 3408 bytes
BITMAP_SIZE = (PRINT_WIDTH_PX // 8) * PRINT_HEIGHT_PX  # 3408

# Label dimensions in mm (P21 label)
LABEL_WIDTH_MM = 15.0
LABEL_HEIGHT_MM = 40.0
LABEL_GAP_MM = 5.0

# Serial defaults
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 5

# Wake / cancel-pause escape sequence
ESC_CANCEL_PAUSE = b"\x1b!o"

# Readiness check
ESC_READY_CHECK = b"\x1b!?"


class NelkoPrinter:
    """Driver for the Nelko P21 thermal label printer (TSPL2 protocol)."""

    def __init__(self, port: str = "COM11", baudrate: int = DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self._serial: serial.Serial | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        """Open the serial connection to the printer."""
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=DEFAULT_TIMEOUT,
            write_timeout=DEFAULT_TIMEOUT,
        )
        time.sleep(0.5)

    def disconnect(self):
        """Close the serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _send_raw(self, data: bytes):
        """Send raw bytes to the printer."""
        if not self.is_connected:
            raise RuntimeError("Not connected to printer")
        self._serial.write(data)

    def _read_response(self, size: int = 256, timeout: float = 1.0) -> bytes:
        """Read available response bytes from the printer."""
        if not self.is_connected:
            return b""
        old_timeout = self._serial.timeout
        self._serial.timeout = timeout
        try:
            time.sleep(0.2)
            if self._serial.in_waiting:
                return self._serial.read(self._serial.in_waiting)
            return b""
        finally:
            self._serial.timeout = old_timeout

    # ------------------------------------------------------------------
    # Printer queries
    # ------------------------------------------------------------------

    def wake(self):
        """Send wake / cancel-pause sequence."""
        self._send_raw(ESC_CANCEL_PAUSE + b"\r\n")
        time.sleep(0.3)
        # Drain any response
        if self._serial.in_waiting:
            self._serial.read(self._serial.in_waiting)

    def check_ready(self) -> int:
        """Check if the printer is ready. Returns 0=ready, 1=lid open, 4=no paper, 32=busy."""
        self._send_raw(ESC_READY_CHECK)
        resp = self._read_response(1, timeout=2.0)
        if resp:
            return resp[0]
        return -1  # no response

    def get_battery(self) -> str:
        """Query battery level. Returns raw response string."""
        self._send_raw(b"BATTERY?\r\n")
        resp = self._read_response()
        return resp.hex() if resp else "(no response)"

    def get_config(self) -> str:
        """Query printer configuration. Returns raw response string."""
        self._send_raw(b"CONFIG?\r\n")
        resp = self._read_response()
        return resp.hex() if resp else "(no response)"

    def probe(self, verbose: bool = True) -> dict:
        """
        Diagnostic probe — tries multiple approaches to communicate with the printer.
        Returns a dict of results for each test.
        """
        results = {}

        def log(msg):
            if verbose:
                print(msg)

        # 1. Drain any stale data
        if self._serial.in_waiting:
            stale = self._serial.read(self._serial.in_waiting)
            log(f"  Drained {len(stale)} stale bytes: {stale.hex()}")

        # 2. Try ESC wake
        log("  Sending ESC cancel-pause (\\x1b!o)...")
        self._send_raw(ESC_CANCEL_PAUSE + b"\r\n")
        time.sleep(0.5)
        resp = b""
        if self._serial.in_waiting:
            resp = self._serial.read(self._serial.in_waiting)
        log(f"  Response: {resp.hex() if resp else '(none)'} ({len(resp)} bytes)")
        results["wake"] = resp

        # 3. Try ESC ready check
        log("  Sending ESC ready check (\\x1b!?)...")
        self._send_raw(ESC_READY_CHECK)
        time.sleep(0.5)
        resp = b""
        if self._serial.in_waiting:
            resp = self._serial.read(self._serial.in_waiting)
        log(f"  Response: {resp.hex() if resp else '(none)'} ({len(resp)} bytes)")
        results["ready"] = resp

        # 4. Try SELFTEST
        log("  Sending SELFTEST...")
        self._send_raw(b"SELFTEST\r\n")
        time.sleep(1.0)
        resp = b""
        if self._serial.in_waiting:
            resp = self._serial.read(self._serial.in_waiting)
        log(f"  Response: {resp.hex() if resp else '(none)'} ({len(resp)} bytes)")
        results["selftest"] = resp

        # 5. Try BATTERY?
        log("  Sending BATTERY?...")
        self._send_raw(b"BATTERY?\r\n")
        time.sleep(0.5)
        resp = b""
        if self._serial.in_waiting:
            resp = self._serial.read(self._serial.in_waiting)
        log(f"  Response: {resp.hex() if resp else '(none)'} ({len(resp)} bytes)")
        results["battery"] = resp

        # 6. Try wake then ready (sequenced)
        log("  Sending wake + ready combo...")
        self._send_raw(ESC_CANCEL_PAUSE + b"\r\n")
        time.sleep(0.3)
        self._send_raw(ESC_READY_CHECK)
        time.sleep(1.0)
        resp = b""
        if self._serial.in_waiting:
            resp = self._serial.read(self._serial.in_waiting)
        log(f"  Response: {resp.hex() if resp else '(none)'} ({len(resp)} bytes)")
        results["wake_then_ready"] = resp

        return results

    # ------------------------------------------------------------------
    # Bitmap conversion
    # ------------------------------------------------------------------

    @staticmethod
    def image_to_bitmap(img: Image.Image) -> bytes:
        """
        Convert a Pillow Image to the printer's native bitmap format.

        Accepts either:
        - Landscape image (284 x 96 or similar) — rotated to portrait automatically
        - Portrait image (96 x 284 or similar) — used as-is

        Returns raw 1-bit bitmap data (3408 bytes), padded with 0xFF (white).
        TSPL2 BITMAP: bit=0 is black, bit=1 is white.
        """
        img = img.copy()

        # If landscape (wider than tall), rotate to portrait for the printer
        if img.width > img.height:
            img = img.rotate(90, expand=True)

        # Resize to fit print area
        img.thumbnail((PRINT_WIDTH_PX, PRINT_HEIGHT_PX), Image.Resampling.NEAREST)

        # Create white canvas at exact print size
        canvas = Image.new("L", (PRINT_WIDTH_PX, PRINT_HEIGHT_PX), 255)
        x_offset = (PRINT_WIDTH_PX - img.width) // 2
        y_offset = (PRINT_HEIGHT_PX - img.height) // 2
        canvas.paste(img.convert("L"), (x_offset, y_offset))

        # Convert to 1-bit: threshold at 128
        # TSPL2 BITMAP: bit=0 means black, bit=1 means white
        raw = bytearray()
        for y in range(PRINT_HEIGHT_PX):
            for x_byte in range(PRINT_WIDTH_PX // 8):
                byte_val = 0
                for bit in range(8):
                    px = canvas.getpixel((x_byte * 8 + bit, y))
                    if px >= 128:  # light pixel = white = 1
                        byte_val |= (0x80 >> bit)
                raw.append(byte_val)

        # Pad with 0xFF (all white)
        while len(raw) < BITMAP_SIZE:
            raw.append(0xFF)

        return bytes(raw[:BITMAP_SIZE])

    # ------------------------------------------------------------------
    # Print command builder
    # ------------------------------------------------------------------

    def _build_print_command(self, bitmap_data: bytes, copies: int = 1,
                             density: int = 15) -> bytes:
        """
        Build the complete print command blob.

        The Nelko P21 expects all commands sent as one continuous blob:
        ESC_CANCEL + SIZE + GAP + DIRECTION + DENSITY + CLS + BITMAP + PRINT
        """
        width_bytes = PRINT_WIDTH_PX // 8  # 12

        cmd = bytearray()
        # Wake / cancel pause
        cmd += ESC_CANCEL_PAUSE + b"\r\n"
        # Label setup
        cmd += f"SIZE {LABEL_WIDTH_MM:.1f} mm,{LABEL_HEIGHT_MM:.1f} mm\r\n".encode()
        cmd += f"GAP {LABEL_GAP_MM:.1f} mm,0 mm\r\n".encode()
        cmd += b"DIRECTION 1,1\r\n"
        cmd += f"DENSITY {min(max(density, 1), 15)}\r\n".encode()
        cmd += b"CLS\r\n"
        # Bitmap: x=0, y=0, width_bytes=12, height=284, mode=1
        cmd += f"BITMAP 0,0,{width_bytes},{PRINT_HEIGHT_PX},1,".encode()
        cmd += bitmap_data
        cmd += b"\r\n"
        cmd += f"PRINT {copies}\r\n".encode()

        return bytes(cmd)

    # ------------------------------------------------------------------
    # High-level print methods
    # ------------------------------------------------------------------

    def print_image(self, img: Image.Image, copies: int = 1, density: int = 15):
        """
        Print a Pillow Image on a label.

        Accepts landscape (wide) or portrait images. The driver handles
        rotation and scaling to fit the 96x284 print area.
        """
        bitmap = self.image_to_bitmap(img)
        cmd = self._build_print_command(bitmap, copies=copies, density=density)
        self._send_raw(cmd)

    def print_file(self, path: str | Path, copies: int = 1, density: int = 15):
        """Load an image file and print it."""
        img = Image.open(str(path))
        self.print_image(img, copies=copies, density=density)

    def print_test_label(self, copies: int = 1):
        """Generate and print a simple test label with text and a border."""
        img = self._generate_test_image()
        self.print_image(img, copies=copies)
        return img

    @staticmethod
    def _generate_test_image() -> Image.Image:
        """Create a landscape test label image (284 x 96)."""
        from PIL import ImageDraw, ImageFont

        img = Image.new("RGB", (LABEL_WIDTH_PX, LABEL_HEIGHT_PX), "white")
        draw = ImageDraw.Draw(img)

        # Border
        draw.rectangle([1, 1, LABEL_WIDTH_PX - 2, LABEL_HEIGHT_PX - 2],
                       outline="black", width=2)

        # Fonts
        font = font_sm = None
        for name in ("arialbd.ttf", "arial.ttf", "consola.ttf"):
            try:
                font = ImageFont.truetype(name, 16)
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default()
        for name in ("arial.ttf", "consola.ttf"):
            try:
                font_sm = ImageFont.truetype(name, 11)
                break
            except OSError:
                continue
        if font_sm is None:
            font_sm = ImageFont.load_default()

        # Left side: title + info
        draw.text((8, 6), "NELKO P21", fill="black", font=font)
        draw.text((8, 26), "Test Label", fill="black", font=font_sm)
        draw.line([(8, 44), (140, 44)], fill="black", width=1)
        draw.text((8, 50), f"{LABEL_WIDTH_PX}x{LABEL_HEIGHT_PX}px", fill="black", font=font_sm)
        draw.text((8, 66), "203 DPI  15x40mm", fill="black", font=font_sm)

        # Vertical divider
        draw.line([(150, 6), (150, LABEL_HEIGHT_PX - 6)], fill="black", width=1)

        # Right side: checkerboard
        sq = 8
        for row in range(min(5, (LABEL_HEIGHT_PX - 16) // sq)):
            for col in range(min(8, (LABEL_WIDTH_PX - 168) // sq)):
                if (row + col) % 2 == 0:
                    x0 = 160 + col * sq
                    y0 = 8 + row * sq
                    draw.rectangle([x0, y0, x0 + sq - 1, y0 + sq - 1], fill="black")

        # Bottom text
        draw.text((8, LABEL_HEIGHT_PX - 20), "OK!", fill="black", font=font)
        draw.text((160, LABEL_HEIGHT_PX - 20), "Landscape", fill="black", font=font_sm)

        return img


# ======================================================================
# CLI test harness
# ======================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Nelko P21 test utility")
    parser.add_argument("-p", "--port", default="COM11", help="Serial port (default: COM11)")
    parser.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUDRATE,
                        help=f"Baud rate (default: {DEFAULT_BAUDRATE})")
    parser.add_argument("--test", action="store_true", help="Print a test label")
    parser.add_argument("--image", type=str, help="Print an image file")
    parser.add_argument("--battery", action="store_true", help="Query battery level")
    parser.add_argument("--config", action="store_true", help="Query printer config")
    parser.add_argument("--ready", action="store_true", help="Check if printer is ready")
    parser.add_argument("--probe", action="store_true",
                        help="Diagnostic probe — tries multiple commands to find what works")
    parser.add_argument("--preview", action="store_true",
                        help="Generate test label and save as PNG (no printer needed)")
    parser.add_argument("--copies", type=int, default=1, help="Number of copies")
    parser.add_argument("--density", type=int, default=15, help="Print density 0-15")

    args = parser.parse_args()

    if args.preview:
        img = NelkoPrinter._generate_test_image()
        out = Path("nelko_test_label.png")
        img.save(str(out), dpi=(203, 203))
        print(f"Preview saved to {out.resolve()}")
        sys.exit(0)

    if not (args.test or args.image or args.battery or args.config or args.ready or args.probe):
        parser.print_help()
        sys.exit(0)

    print(f"Connecting to Nelko P21 on {args.port} @ {args.baud} baud...")
    try:
        with NelkoPrinter(args.port, args.baud) as printer:
            print("Connected.")

            if args.probe:
                print("Running diagnostic probe...")
                printer.probe(verbose=True)
                print("Probe complete.")

            if args.ready:
                status = printer.check_ready()
                status_map = {0: "Ready", 1: "Lid open", 4: "No paper", 32: "Busy", -1: "No response"}
                print(f"Status: {status_map.get(status, f'Unknown ({status})')}")

            if args.battery:
                resp = printer.get_battery()
                print(f"Battery: {resp}")

            if args.config:
                resp = printer.get_config()
                print(f"Config: {resp}")

            if args.image:
                print(f"Printing image: {args.image}")
                printer.print_file(args.image, copies=args.copies, density=args.density)
                print("Sent.")

            if args.test:
                print("Printing test label...")
                printer.print_test_label(copies=args.copies)
                print("Sent.")

    except serial.SerialException as e:
        print(f"Serial error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
