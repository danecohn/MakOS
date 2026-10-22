#!/usr/bin/env python3
"""Validate originals and emit the redistributable MakOS icon theme.

No alpha invention, no background removal. --normalize is explicit resizing of
AI outputs to the requested canonical resolution. Report includes source size.
"""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
SIZES=(512,256,128,64,48,32,16)
APP_NAMES='files terminal text-editor calculator preview notes calendar clock activity disk-utility screenshot system-info software-center photos music video settings seek widgets trash-empty trash-full desktops spread browser mail contacts maps rewind dictionary app-store'.split()
FILE_NAMES='folder folder-open folder-documents folder-downloads folder-pictures folder-music folder-movies folder-applications folder-desktop folder-network drive-internal drive-external drive-optical drive-network file-generic file-text file-pdf file-image file-audio file-video file-archive file-code file-spreadsheet file-presentation file-document'.split()
NAMES=APP_NAMES+FILE_NAMES

def validate_icon(image,name,canonical=True):
    if image.mode!='RGBA':
        raise ValueError(f'{name}: RGBA required')
    if canonical and image.size!=(1024,1024):
        raise ValueError(f'{name}: expected 1024x1024, got {image.size}')
    if image.width!=image.height:
        raise ValueError(f'{name}: square canvas required')
    alpha=image.getchannel('A')
    lo,hi=alpha.getextrema()
    if lo!=0 or hi<200:
        raise ValueError(f'{name}: missing transparent background or opaque content')
    bbox=alpha.point(lambda x:255 if x>32 else 0).getbbox()
    if not bbox or bbox[0]==0 or bbox[1]==0 or bbox[2]==image.width or bbox[3]==image.height:
        raise ValueError(f'{name}: opaque content touches canvas edge')
    cx=(bbox[0]+bbox[2])/2/image.width
    cy=(bbox[1]+bbox[3])/2/image.height
    if abs(cx-.5)>.14 or abs(cy-.5)>.14:
        raise ValueError(f'{name}: object is off-center')
    return {'bbox':bbox,'center':[round(cx,3),round(cy,3)]}


def ingest(source,target,normalize=False,require_all=False):
    report={'generated':[],'missing':[],'errors':[]}
    for name in NAMES:
        path=source/(name+'.png')
        if not path.exists():
            report['missing'].append(name)
            continue
        try:
            with Image.open(path) as source_image:
                image=source_image.copy()
            original=list(image.size)
            validate_icon(image,name,canonical=not normalize)
            if normalize and image.size!=(1024,1024):
                image=image.resize((1024,1024),Image.Resampling.LANCZOS)
                image.save(path)
            info=validate_icon(image,name)
            for size in SIZES:
                dest=target/f'{size}x{size}/apps'/f'{name}.png'
                dest.parent.mkdir(parents=True,exist_ok=True)
                image.resize((size,size),Image.Resampling.LANCZOS).save(dest)
            report['generated'].append({'name':name,'source_size':original,**info})
        except (ValueError,OSError) as error:
            report['errors'].append(str(error))
    dirs=[f'{s}x{s}/apps' for s in SIZES]+['scalable/apps']
    index=['[Icon Theme]','Name=MakOS','Comment=Original Glass & Metal icons','Inherits=hicolor','Directories='+','.join(dirs),'']
    for s in SIZES:
        index += [f'[{s}x{s}/apps]',f'Size={s}','Type=Fixed','Context=Applications','']
    index += ['[scalable/apps]','Size=64','Type=Scalable','MinSize=16','MaxSize=512','Context=Applications','']
    target.mkdir(parents=True,exist_ok=True)
    (target/'index.theme').write_text('\n'.join(index))
    (target/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['errors'] or (require_all and report['missing']):
        raise ValueError(json.dumps(report,indent=2))
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,default=ROOT/'assets/makos')
    ap.add_argument('--target',type=Path,default=ROOT/'src/makos/icons/MakOS')
    ap.add_argument('--normalize',action='store_true')
    ap.add_argument('--require-all',action='store_true')
    args=ap.parse_args()
    try:
        result=ingest(args.source,args.target,args.normalize,args.require_all)
    except ValueError as error:
        ap.exit(1,str(error)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
