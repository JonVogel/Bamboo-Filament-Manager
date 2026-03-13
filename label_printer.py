# -*- coding: utf-8 -*-

# Generate and print spool ID labels for Nelko P21 (15x40mm) or similar label printers.

import io
import os
import tempfile
from pathlib import Path

import barcode
from barcode.writer import ImageWriter
import qrcode
from PIL import Image, ImageDraw, ImageFont
from PyQt6.QtCore import QSettings


# Nelko P21 label: 15mm x 40mm at 203 DPI
# Landscape: 284 wide x 96 tall (actual printer pixels, no scaling)
LABEL_W = 284
LABEL_H = 96


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a monospace or sans-serif font at the given size."""
    for name in ("consolab.ttf", "consola.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_barcode(data: str, barcode_type: str, max_w: int, max_h: int) -> Image.Image | None:
    """Render a QR code or Code 128 barcode image, sized to fit."""
    if barcode_type == "code128":
        # Code 128 — tune module_width so the native pixel width ≈ target
        # At 203 DPI, module_width=0.3mm gives ~284px for an 8-char payload
        writer = ImageWriter()
        code = barcode.get("code128", data, writer=writer)
        # Binary search for the module_width that best matches max_w
        best_mw, best_img = 0.3, None
        for mw_x10 in range(15, 50):  # 0.15 to 0.49
            mw = mw_x10 / 100
            buf = io.BytesIO()
            code.write(buf, options={
                "module_width": mw,
                "module_height": max_h * 25.4 / 203,  # px to mm at 203 DPI
                "quiet_zone": 1,
                "font_size": 0,
                "text_distance": 0,
                "write_text": False,
                "dpi": 203,
            })
            buf.seek(0)
            img = Image.open(buf).convert("RGB")
            if img.width <= max_w:
                best_mw, best_img = mw, img
            else:
                break
        if best_img is None:
            return None
        # Crop any extra whitespace height, then pad/center to exact max_h
        return best_img.crop((0, 0, best_img.width, max_h))
    else:
        # QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=3,
            border=1,
        )
        qr.add_data(data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        render_size = min(max_w, max_h)
        return qr_img.resize((render_size, render_size), Image.Resampling.NEAREST)


def _layout_qr(img, draw, spool_id, spool_num, dtype, color_name):
    """QR layout: text on left, QR code on right."""
    font_big = _get_font(32)
    font_med = _get_font(18)

    qr_size = LABEL_H - 6
    text_area_w = LABEL_W - qr_size - 14
    y, x_left = 2, 3

    draw.text((x_left, y), spool_id, fill="black", font=font_big)
    y += 34
    draw.line([(x_left, y), (text_area_w - 2, y)], fill="black", width=1)
    y += 4

    if dtype:
        for line in _wrap_text(draw, dtype, font_med, text_area_w - x_left - 2):
            draw.text((x_left, y), line, fill="black", font=font_med)
            y += 20
    if color_name:
        draw.text((x_left, y), color_name, fill="black", font=font_med)

    if spool_num:
        code_img = _render_barcode(spool_id, "qr", qr_size, qr_size)
        if code_img:
            code_x = LABEL_W - code_img.width - 3
            code_y = (LABEL_H - code_img.height) // 2
            img.paste(code_img, (code_x, code_y))
            div_x = code_x - 4
            draw.line([(div_x, 3), (div_x, LABEL_H - 3)], fill="black", width=1)


def _layout_1d(img, draw, spool_id, spool_num, dtype, color_name):
    """1D layout: barcode across the top, spool ID bottom-left, type+color bottom-right."""
    font_id = _get_font(28)
    font_sm = _get_font(14)

    bar_h = 45  # barcode region height
    pad = 3

    # Barcode across the top
    if spool_num:
        code_img = _render_barcode(spool_id, "code128", LABEL_W - 6, bar_h - 4)
        if code_img:
            bx = (LABEL_W - code_img.width) // 2
            img.paste(code_img, (bx, 2))

    # Divider line below barcode
    div_y = bar_h + 1
    draw.line([(pad, div_y), (LABEL_W - pad, div_y)], fill="black", width=1)

    # Bottom half: spool ID on left, type + color on right
    bottom_y = div_y + 3

    # Spool ID — left side
    draw.text((pad, bottom_y), spool_id, fill="black", font=font_id)

    # Measure spool ID width for the divider
    id_bbox = draw.textbbox((0, 0), spool_id, font=font_id)
    id_w = id_bbox[2] - id_bbox[0]
    mid_x = pad + id_w + 6

    # Vertical divider
    draw.line([(mid_x, div_y + 2), (mid_x, LABEL_H - pad)], fill="black", width=1)

    # Type + color — right side
    rx = mid_x + 5
    right_w = LABEL_W - rx - pad
    ry = bottom_y
    if dtype:
        for line in _wrap_text(draw, dtype, font_sm, right_w):
            draw.text((rx, ry), line, fill="black", font=font_sm)
            ry += 16
    if color_name:
        draw.text((rx, ry), color_name, fill="black", font=font_sm)


def generate_label(entry: dict) -> Path:
    """Create a landscape label image for a filament spool. Returns the temp file path."""
    spool_num = entry.get("spool_number", 0)
    spool_id = f"SPL-{spool_num:04d}" if spool_num else "SPL-????"
    entry_id = entry.get("id", "")
    dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "")
    color_name = entry.get("color_name", "")

    barcode_type = QSettings().value("printer/barcode_type", "qr")

    img = Image.new("RGB", (LABEL_W, LABEL_H), "white")
    draw = ImageDraw.Draw(img)

    if barcode_type == "code128":
        _layout_1d(img, draw, spool_id, spool_num, dtype, color_name)
    else:
        _layout_qr(img, draw, spool_id, spool_num, dtype, color_name)

    # Convert to pure 1-bit monochrome — no gray pixels, no anti-aliasing.
    # This gives the thermal printer the crispest possible input.
    img = img.convert("1")

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(
        suffix=".png", prefix=f"spool_{spool_id}_", delete=False,
    )
    tmp.close()
    img.save(tmp.name, dpi=(203, 203))
    return Path(tmp.name)


def print_label(entry: dict):
    """Generate a label and send it to the default printer via Windows shell."""
    path = generate_label(entry)
    os.startfile(str(path), "print")


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Simple word-wrap for a string."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]
