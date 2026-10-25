#!/usr/bin/env python3
"""Render original Artemis Softworks LLC/Makk OS brand assets from the source SVG."""
from pathlib import Path
import math
import gi
gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'src/makos/theme/plymouth'
logo=ROOT/'src/makos/branding/cherry-blossom.svg'
pix=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(logo),128,128,True)
pix.savev(str(OUT/'blossom.png'),'png',[],[])
flower=Image.open(OUT/'blossom.png').convert('RGBA')
mark=Image.new('RGBA',(420,240));mark.alpha_composite(flower,(146,0));d=ImageDraw.Draw(mark)
font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
d.text((210,150),'Makk OS',font=ImageFont.truetype(font,34),fill='#253c50',anchor='mm')
d.text((210,194),'Artemis Softworks LLC',font=ImageFont.truetype(font,15),fill='#4c6375',anchor='mm')
mark.save(OUT/'watermark.png')
# Two-step's native progress, authentication and message handling stays in charge.
for i in range(36):
 im=Image.new('RGBA',(32,32));draw=ImageDraw.Draw(im)
 draw.arc((5,5,27,27),0,360,fill='#a4b6c4',width=3)
 draw.arc((5,5,27,27),i*10,i*10+90,fill='#ff0058',width=3)
 im.save(OUT/f'animation-{i+1:04}.png')
# Native two-step lock, caps-lock and entry artwork must exist for disk-unlock prompts.
for name in ('lock','capslock','keyboard','keymap','bullet','entry'):
 im=Image.new('RGBA',(24,24) if name!='entry' else (220,34));draw=ImageDraw.Draw(im)
 if name=='entry':draw.rounded_rectangle((0,0,219,33),5,fill='#f4f7fa',outline='#718696')
 elif name=='bullet':draw.ellipse((9,9,15,15),fill='#253c50')
 elif name=='lock':
  draw.arc((7,2,17,15),180,360,fill='#253c50',width=2);draw.rounded_rectangle((4,10,20,23),3,fill='#536d81')
 else:draw.rounded_rectangle((2,5,22,20),3,outline='#536d81',width=2)
 im.save(OUT/(name+'.png'))
preview=Image.new('RGBA',(1280,800),'#c4d1dc');preview.alpha_composite(mark,(430,216));preview.convert('RGB').save(OUT/'preview.png')
print('Rendered Artemis Softworks/Makk OS brand assets')
