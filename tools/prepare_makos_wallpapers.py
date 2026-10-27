#!/usr/bin/env python3
"""Explicit wallpaper resampling; preserve source pixels and report native dimensions."""
import json
from pathlib import Path
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
NAMES=('nave-night','nave-dawn','ridge-night','ridge-dawn','starfall-night','starfall-dawn','rose-window-night','rose-window-dawn')

def main():
    target=ROOT/'src/makos/wallpapers'
    (target/'previews').mkdir(parents=True,exist_ok=True)
    report=[]
    for name in NAMES:
        src=ROOT/'assets/makos'/f'wallpaper-{name}.jpg'
        if not src.exists():continue
        with Image.open(src) as image:
            original=image.size
            output=ImageOps.fit(image.convert('RGB'),(3840,2160),Image.Resampling.LANCZOS)
            output.save(target/f'wallpaper-{name}.jpg',quality=94,optimize=True)
            output.thumbnail((426,240),Image.Resampling.LANCZOS)
            output.save(target/'previews'/f'wallpaper-{name}.jpg',quality=88)
            report.append({'file':src.name,'native_size':original,'output_size':[3840,2160],'resampled':original!=(3840,2160)})
    (target/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Prepared',len(report),'wallpapers; native resolution is recorded separately')
if __name__=='__main__':main()
