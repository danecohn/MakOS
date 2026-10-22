"""Boot splash for new projects: neon sun over a perspective grid, drawn with PIL (or Qt/pure-python fallback)."""
import struct
import zlib
from pathlib import Path


def _png_fallback(path, w, h):
    rows = []
    for y in range(h):
        t = y / h
        r, g, b = int(14 + 70 * t), int(8 + 20 * t), int(16 + 40 * t)
        rows.append(b'\x00' + bytes([r, g, b]) * w)
    raw = b''.join(rows)
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def make_splash(path, title='Engine', w=640, h=360):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        _png_fallback(path, w, h)
        return path
    img = Image.new('RGB', (w, h), (14, 8, 16))
    d = ImageDraw.Draw(img)
    horizon = int(h * 0.62)
    for y in range(horizon):
        t = y / horizon
        d.line([(0, y), (w, y)], fill=(int(30 + 40 * t), int(15 + 10 * t), int(40 + 30 * t)))
    cx, r = w // 2, int(h * 0.26)
    for i in range(r * 2):
        y = horizon - r * 2 + i
        t = i / (r * 2)
        half = (r * r - (r - i / 2) ** 2) ** 0.5 if abs(r - i / 2) < r else 0
        col = (255, int(176 - 110 * t), int(46 + 64 * t))
        if i % 9 < 6 or t < 0.4:
            d.line([(cx - half, y), (cx + half, y)], fill=col)
    d.rectangle([0, horizon, w, h], fill=(14, 8, 16))
    for k in range(-12, 13):
        d.line([(cx, horizon), (cx + k * w // 6, h)], fill=(255, 176, 46))
    for k in range(1, 7):
        y = horizon + int((k / 7) ** 2 * (h - horizon))
        d.line([(0, y), (w, y)], fill=(255, 176, 46))
    d.text((w // 2 - len(title) * 3, int(h * 0.1)), title.upper(), fill=(255, 240, 207))
    d.text((w // 2 - 84, h - 18), 'powered by the Godot Engine (MIT)', fill=(160, 150, 190))
    img.save(path)
    return path
