"""Boot splash for new projects: Artemis crescent-and-bow on a coastal gradient, drawn with PIL (or Qt/pure-python fallback)."""
import struct
import zlib
from pathlib import Path


def _png_fallback(path, w, h):
    rows = []
    for y in range(h):
        t = y / h
        r, g, b = int(20 + 15 * t), int(37 + 22 * t), int(47 + 19 * t)
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
    img = Image.new('RGB', (w, h), (20, 37, 47))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=(int(20 + 15*t), int(37 + 22*t), int(47 + 19*t)))
    emblem = Path(__file__).with_name('artemis.png')
    if emblem.exists():
        logo = Image.open(emblem).convert('RGBA')
        side = int(h * 0.60)
        logo = logo.resize((side, side), Image.Resampling.LANCZOS)
        img.paste(logo, ((w-side)//2, (h-side)//2-8), logo)
    d.text((w // 2 - len(title) * 3, int(h * 0.10)), title.upper(), fill=(237, 239, 223))
    d.text((20, h-33), 'A product of Artemis Softworks LLC', fill=(188, 204, 195))
    d.text((20, h-18), 'Powered by the Godot Engine (MIT)', fill=(148, 169, 169))
    img.save(path)
    return path
