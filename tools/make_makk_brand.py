#!/usr/bin/env python3
"""Render the VigilOS boot/login brand assets (Plymouth) from the VigilTech icon kit and Vigil Sans."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'src/makos/theme/plymouth'
BRAND=ROOT/'brand/vigiltech'
OUT.mkdir(parents=True,exist_ok=True)
mark_icon=Image.open(BRAND/'icons/os-256.png').convert('RGBA').resize((128,128),Image.Resampling.LANCZOS)
mark_icon.save(OUT/'mark.png')
bold=ImageFont.truetype(str(BRAND/'fonts/VigilSans-Bold.ttf'),34)
regular=ImageFont.truetype(str(BRAND/'fonts/VigilSans-Regular.ttf'),15)
mark=Image.new('RGBA',(420,240));mark.alpha_composite(mark_icon,(146,0));d=ImageDraw.Draw(mark)
d.text((210,150),'VigilOS',font=bold,fill='#f7eef2',anchor='mm')
d.text((210,194),'A product of VigilTech',font=regular,fill='#d9c8d3',anchor='mm')
mark.save(OUT/'watermark.png')
# Two-step's native progress, authentication and message handling stays in charge.
for i in range(36):
 im=Image.new('RGBA',(32,32));draw=ImageDraw.Draw(im)
 draw.arc((5,5,27,27),0,360,fill='#5a3f58',width=3)
 draw.arc((5,5,27,27),i*10,i*10+90,fill='#ff4d86',width=3)
 im.save(OUT/f'animation-{i+1:04}.png')
# Native two-step lock, caps-lock and entry artwork must exist for disk-unlock prompts.
for name in ('lock','capslock','keyboard','keymap','bullet','entry'):
 im=Image.new('RGBA',(24,24) if name!='entry' else (220,34));draw=ImageDraw.Draw(im)
 if name=='entry':draw.rounded_rectangle((0,0,219,33),8,fill='#fffbfd',outline='#8f7b8b')
 elif name=='bullet':draw.ellipse((9,9,15,15),fill='#f7eef2')
 elif name=='lock':
  draw.arc((7,2,17,15),180,360,fill='#f7eef2',width=2);draw.rounded_rectangle((4,10,20,23),3,fill='#d9c8d3')
 else:draw.rounded_rectangle((2,5,22,20),3,outline='#d9c8d3',width=2)
 im.save(OUT/(name+'.png'))
preview=Image.new('RGBA',(1280,800),'#120a14');preview.alpha_composite(mark,(430,216));preview.convert('RGB').save(OUT/'preview.png')
print('Rendered VigilOS brand assets')
