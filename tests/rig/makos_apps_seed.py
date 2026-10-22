"""Create deterministic sample data under $HOME for the core-app rig (never touches real user folders)."""
import datetime as dt
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path


def seed(home):
    home = Path(home)
    pics, music, videos, docs = home / 'Pictures', home / 'Music', home / 'Videos', home / 'Documents'
    for d in (pics / 'Holiday', pics / 'Screenshots', music / 'Demo Band' / 'First Album', videos, docs):
        d.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw
    palette = [((30, 90, 160), (200, 230, 255)), ((160, 60, 40), (255, 220, 160)), ((40, 120, 70), (200, 255, 210)), ((90, 50, 140), (230, 210, 255)), ((20, 20, 30), (250, 200, 80))]
    for i in range(10):
        top, bottom = palette[i % len(palette)]
        im = Image.new('RGB', (900 + 40 * i, 600))
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                t = y / im.height
                px[x, y] = tuple(int(top[c] * (1 - t) + bottom[c] * t) for c in range(3))
        d = ImageDraw.Draw(im)
        d.ellipse((120 + 30 * i, 120, 420 + 30 * i, 420), fill=(255, 255, 255))
        d.rectangle((500, 200 + 10 * i, 800, 400), outline=(255, 255, 255), width=6)
        target = (pics / 'Holiday' if i % 2 else pics) / f'sample-{i + 1:02d}.jpg'
        im.save(target, quality=90)
        stamp = dt.datetime(2026, 8 + i % 3, 1 + i).timestamp()
        os.utime(target, (stamp, stamp))
    rate = 22050
    for n, (artist, title, hz) in enumerate([('Demo Band', 'Morning Light', 220), ('Demo Band', 'Second Song', 330), ('Demo Band', 'Third Tone', 440)]):
        path = music / 'Demo Band' / 'First Album' / f'{n + 1:02d} - {artist} - {title}.wav'
        with wave.open(str(path), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b''.join(struct.pack('<h', int(9000 * math.sin(2 * math.pi * hz * i / rate))) for i in range(rate * 6)))
    video = videos / 'test-pattern.ogv'
    gst = shutil.which('gst-launch-1.0')
    if gst:
        subprocess.run([gst, '-q', 'videotestsrc', 'num-buffers=300', 'pattern=ball', '!', 'video/x-raw,width=480,height=270,framerate=15/1', '!', 'videoconvert', '!', 'theoraenc', '!', 'oggmux', 'name=m',
                        '!', 'filesink', f'location={video}', 'audiotestsrc', 'num-buffers=430', 'freq=300', '!', 'audioconvert', '!', 'vorbisenc', '!', 'm.'], check=False, timeout=90, capture_output=True)
        (videos / 'test-pattern.srt').write_text('1\n00:00:00,500 --> 00:00:09,000\nMakkOS subtitle test line\n\n2\n00:00:10,000 --> 00:00:19,000\nSecond subtitle\n')
    import cairo
    pdf = docs / 'Sample.pdf'
    surface = cairo.PDFSurface(str(pdf), 420, 560)
    c = cairo.Context(surface)
    for page in range(1, 4):
        c.set_source_rgb(1, 1, 1)
        c.paint()
        c.set_source_rgb(.1, .15, .3)
        c.select_font_face('DejaVu Sans')
        c.set_font_size(34)
        c.move_to(40, 90)
        c.show_text(f'Sample page {page}')
        c.set_font_size(14)
        for line in range(12):
            c.move_to(40, 140 + line * 24)
            c.show_text('MakkOS Preview renders this paragraph line %d of the test document.' % line)
        surface.show_page()
    surface.finish()
    (docs / 'Welcome.txt').write_text('A private rig document.\nSecond line to edit.\nThird line.\n')
    return {'pictures': pics, 'music': music, 'videos': videos, 'pdf': pdf, 'text': docs / 'Welcome.txt', 'video': video}


if __name__ == '__main__':
    print(seed(sys.argv[1]))
