#!/usr/bin/env python3
"""Original mathematical UI materials, sounds and cursor artwork. GPL-3.0-only."""
import math
import struct
import wave
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/makos'
THEME=ROOT/'src/makos/theme/materials'

def gradient(name,size,top,bottom,alpha=255):
    w,h=size
    image=Image.new('RGBA',size)
    draw=ImageDraw.Draw(image)
    for y in range(h):
        t=y/(h-1)
        color=tuple(round(a+(b-a)*t) for a,b in zip(top,bottom))+(alpha,)
        draw.line((0,y,w,y),fill=color)
    image.save(OUT/(name+'.png'))
    return image

def tile(name,size,kind):
    image=Image.new('RGB',(size,size))
    pixels=image.load()
    for y in range(size):
        for x in range(size):
            # All frequencies are integers over size-1; first/last edge samples match.
            sx=x/(size-1)*2*math.pi
            sy=y/(size-1)*2*math.pi
            if kind=='metal':v=207+3*math.sin(sy*43)+2*math.sin(sy*71)+math.cos(sx*5)*.8
            elif kind=='linen':v=219+4*math.sin(sx*47)*math.cos(sy*47)+2*math.sin(sy*83)+2*math.sin(sx*83)
            elif kind=='stripe':v=242+4*math.cos(sy*16)
            else:v=220+4*math.sin(sx)+3*math.cos(sy)
            base=max(0,min(255,round(v)))
            pixels[x,y]=(base,base,min(255,base+2))
    image.save(OUT/(name+'.png'))


def rounded_material(name,size,top,bottom,radius=12):
    image=gradient(name,size,top,bottom)
    mask=Image.new('L',size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,size[0]-1,size[1]-1),radius=radius,fill=255,outline=180)
    image.putalpha(mask)
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((.5,.5,size[0]-1.5,size[1]-1.5),radius=radius,outline='#8b9aab',width=1)
    image.save(OUT/(name+'.png'))


def sounds():
    dest=ROOT/'src/makos/sounds'
    dest.mkdir(parents=True,exist_ok=True)
    for name,tones in [('notification',[(784,.0),(1176,.055)]),('login',[(392,.0),(588,.08),(784,.16)]),('trash',[(220,.0),(165,.04)]),('error',[(294,.0),(277,.13)])]:
        rate=44100;duration=.7
        with wave.open(str(dest/(name+'.wav')),'wb') as f:
            f.setparams((1,2,rate,0,'NONE','not compressed'))
            data=[]
            for i in range(round(rate*duration)):
                t=i/rate;value=0
                for freq,start in tones:
                    s=t-start
                    if s>=0:
                        env=min(1,s/.008)*math.exp(-s*11)
                        value+=(math.sin(2*math.pi*freq*s)+.14*math.sin(2*math.pi*freq*2*s))*env*.12
                data.append(struct.pack('<h',round(max(-1,min(1,value))*32767)))
            f.writeframes(b''.join(data))


def cursor(name,drawfn,hot=(3,2),frames=1):
    dest=ROOT/'src/makos/cursors'
    dest.mkdir(parents=True,exist_ok=True)
    config=[]
    for frame in range(frames):
        for size in (24,32,48,64):
            image=Image.new('RGBA',(128,128))
            draw=ImageDraw.Draw(image)
            drawfn(draw,frame)
            image=image.resize((size,size),Image.Resampling.LANCZOS)
            path=dest/f'{name}-{size}-{frame}.png'
            image.save(path)
            config.append(f'{size} {round(hot[0]*size/32)} {round(hot[1]*size/32)} {path.name}'+(' 70' if frames>1 else ''))
    (dest/(name+'.cursor')).write_text('\n'.join(config)+'\n')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for name,size,kind in [('texture-brushed-metal',512,'metal'),('texture-pinstripe',64,'stripe'),('texture-linen',512,'linen'),('texture-sidebar-glass',256,'glass')]:
        tile(name,size,kind)
    for name,size,a,b in [('menubar-gradient',(8,24),(255,255,255),(218,226,235)),('menubar-gradient-hidpi',(8,48),(255,255,255),(218,226,235)),('title-gradient-active',(8,40),(250,250,251),(201,205,211)),('title-gradient-inactive',(8,40),(246,246,247),(224,226,230)),('toolbar-gradient',(8,64),(248,249,250),(211,215,220))]:
        gradient(name,size,a,b)
    for name,a,b in [('button-gel-default',(210,241,255),(86,160,237)),('button-gel-normal',(255,255,255),(219,224,230)),('button-gel-pressed',(76,129,183),(151,202,241)),('button-gel-disabled',(239,240,241),(221,224,227))]:
        rounded_material(name,(128,64),a,b,15)
    for name,color in [('close',(235,103,88)),('minimize',(224,179,57)),('zoom',(114,184,84))]:
        for state in ('active','inactive','hover'):
            im=Image.new('RGBA',(96,96));d=ImageDraw.Draw(im)
            c=color if state!='inactive' else (182,190,198)
            for radius in range(40,0,-1):
                t=radius/40
                shade=tuple(round(v+(255-v)*(1-t)*.5) for v in c)+(255,)
                d.ellipse((48-radius,48-radius,48+radius,48+radius),fill=shade)
            d.ellipse((21,14,62,38),fill=(255,255,255,155))
            if state=='hover':
                d.line((35,48,61,48),fill='#364957',width=3)
                if name=='zoom':d.line((48,35,48,61),fill='#364957',width=3)
                if name=='close':
                    d.ellipse((31,31,65,65),fill=c+(255,))
                    d.line((36,36,60,60),fill='#364957',width=3);d.line((36,60,60,36),fill='#364957',width=3)
            im.save(OUT/f'traffic-light-{name}-{state}.png')
    rounded_material('scrollbar-thumb',(24,80),(226,238,248),(141,165,188),11)
    rounded_material('badge-red',(64,40),(255,171,160),(201,54,55),20)
    rounded_material('login-avatar-frame',(160,160),(252,254,255),(167,187,204),80)
    rounded_material('dock-shelf-flat',(2048,128),(241,249,255),(136,159,181),24)
    rounded_material('dock-shelf-3d',(2048,256),(235,245,253),(123,146,171),28)
    gradient('dock-reflection-mask',(16,128),(255,255,255),(0,0,0))
    # Render the code-native original geometric logo through the system SVG decoder.
    import gi
    gi.require_version('GdkPixbuf','2.0')
    from gi.repository import GdkPixbuf
    logo=ROOT/'src/makos/icons/MakOS/scalable/apps/makos-makos-logo.svg'
    pix=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(logo),1024,1024,True)
    pix.savev(str(OUT/'makos-logo.png'),'png',[],[])
    mono=Image.open(OUT/'makos-logo.png').convert('RGBA');gray=Image.new('RGBA',mono.size,'#4c6276');gray.putalpha(mono.getchannel('A'));gray.save(OUT/'makos-logo-mono.png')
    THEME.mkdir(parents=True,exist_ok=True)
    for path in OUT.glob('*.png'):
        if path.name.startswith(('texture-','menubar-','title-gradient','toolbar-','button-','traffic-','scrollbar-','badge-','login-','dock-','makos-logo')):
            import shutil
            shutil.copy2(path,THEME/path.name)
    sounds()
    cursor('arrow',lambda d,f:d.polygon([(12,8),(12,100),(35,78),(52,112),(68,104),(52,70),(84,70)],fill='#e5f2fb',outline='#28475d',width=5))
    cursor('ibeam',lambda d,f:(d.line((64,12,64,112),fill='#28475d',width=6),d.line((44,12,84,12),fill='#28475d',width=6),d.line((44,112,84,112),fill='#28475d',width=6)),(16,16))
    cursor('crosshair',lambda d,f:(d.line((64,12,64,116),fill='#3d5e77',width=5),d.line((12,64,116,64),fill='#3d5e77',width=5)),(16,16))
    cursor('pointer-hand',lambda d,f:(d.rounded_rectangle((44,18,60,88),8,fill='#edf7fd',outline='#28475d',width=4),d.rounded_rectangle((38,52,96,111),12,fill='#edf7fd',outline='#28475d',width=4)),(13,5))
    for name in ('resize-horizontal','resize-vertical','resize-diagonal-1','resize-diagonal-2'):
        def render(d,f,name=name):
            points=[(12,64),(37,40),(37,54),(91,54),(91,40),(116,64),(91,88),(91,74),(37,74),(37,88)]
            if name=='resize-vertical':points=[(y,x) for x,y in points]
            elif name.startswith('resize-diagonal'):
                angle=math.pi/4*(1 if name.endswith('1') else -1)
                points=[(64+(x-64)*math.cos(angle)-(y-64)*math.sin(angle),64+(x-64)*math.sin(angle)+(y-64)*math.cos(angle)) for x,y in points]
            d.polygon(points,fill='#e5f2fb',outline='#28475d',width=4)
        cursor(name,render,(16,16))
    def spinner(d,f):
        for n in range(12):
            angle=n*math.pi/6
            x,y=64+33*math.cos(angle),64+33*math.sin(angle)
            a=round(50+205*((n-f)%12)/11)
            d.ellipse((x-6,y-6,x+6,y+6),fill=(65,107,142,a))
    cursor('busy-spinner',spinner,(16,16),12)
    print('Created original UI materials, 4 sounds and cursor source artwork')
if __name__=='__main__':main()
