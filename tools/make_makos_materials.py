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


def _vgrad(size,stops):
    """Vertical RGBA gradient through (t, (r,g,b,a)) stops."""
    w,h=size
    image=Image.new('RGBA',size)
    draw=ImageDraw.Draw(image)
    for y in range(h):
        t=y/max(1,h-1)
        for (t0,c0),(t1,c1) in zip(stops,stops[1:]):
            if t0<=t<=t1:
                k=(t-t0)/max(1e-9,t1-t0)
                draw.line((0,y,w,y),fill=tuple(round(a+(b-a)*k) for a,b in zip(c0,c1)))
                break
    return image

def _slice_shelf(name,image,cap):
    """Save left cap, a 16-px stretchable middle and the right cap; also the stitched full-width image."""
    w,h=image.size
    parts={'left':image.crop((0,0,cap,h)),'mid':image.crop((w//2-8,0,w//2+8,h)),'right':image.crop((w-cap,0,w,h))}
    for suffix,part in parts.items():
        part.save(OUT/f'{name}-{suffix}.png')
    full=Image.new('RGBA',(2048,h))
    full.paste(parts['left'],(0,0))
    for x in range(cap,2048-cap,16):
        full.paste(parts['mid'],(x,0))
    full.paste(parts['right'],(2048-cap,0))
    full.save(OUT/f'{name}.png')

def dock_shelves():
    """Original shelf artwork for the Launcher Bar, drawn with 4x supersampling.
    dock-shelf-flat-*: 2D glass slab. dock-shelf-3d-*: perspective glass floor (far edge narrow, near edge wide)."""
    ss=4
    # ---- 2D glass slab
    W,H,cap,radius=480,128,64,30
    w,h=W*ss,H*ss
    body=_vgrad((w,h),[(0,(238,246,254,170)),(.48,(196,213,232,166)),(.5,(172,194,218,176)),(1,(138,163,192,196))])
    gloss=_vgrad((w,h),[(0,(255,255,255,92)),(.46,(255,255,255,16)),(.47,(255,255,255,0)),(1,(255,255,255,0))])
    body=Image.alpha_composite(body,gloss)
    edge=Image.new('RGBA',(w,h),(0,0,0,0))
    d=ImageDraw.Draw(edge)
    d.rounded_rectangle((0,0,w-1,h-1),radius=radius*ss,outline=(255,255,255,215),width=2*ss)
    d.rounded_rectangle((3*ss,3*ss,w-1-3*ss,h-1-3*ss),radius=(radius-3)*ss,outline=(58,90,128,62),width=ss)
    body=Image.alpha_composite(body,edge)
    mask=Image.new('L',(w,h),0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=radius*ss,fill=255)
    alpha=body.getchannel('A')
    from PIL import ImageChops
    body.putalpha(ImageChops.multiply(alpha,mask))
    _slice_shelf('dock-shelf-flat',body.resize((W,H),Image.Resampling.LANCZOS),cap)
    # ---- 3D glass floor
    W,H,cap,inset=640,256,176,84
    w,h=W*ss,H*ss
    floor=_vgrad((w,h),[(0,(196,222,250,128)),(.5,(150,186,224,168)),(.86,(222,236,251,222)),(.88,(250,253,255,244)),(1,(104,136,176,250))])
    shape=[(inset*ss,0),((W-inset)*ss,0),(w-1,h-1),(0,h-1)]
    mask=Image.new('L',(w,h),0)
    ImageDraw.Draw(mask).polygon(shape,fill=255)
    lines=Image.new('RGBA',(w,h),(0,0,0,0))
    dl=ImageDraw.Draw(lines)
    dl.line(shape+[shape[0]],fill=(255,255,255,170),width=3*ss)
    dl.line((inset*ss,2*ss,(W-inset)*ss,2*ss),fill=(255,255,255,235),width=3*ss)
    floor=Image.alpha_composite(floor,lines)
    floor.putalpha(ImageChops.multiply(floor.getchannel('A'),mask))
    _slice_shelf('dock-shelf-3d',floor.resize((W,H),Image.Resampling.LANCZOS),cap)

def decoration_images():
    """Orbs and a brushed-metal tile for the KWin decoration (1x and @2x), original procedural art."""
    dest=ROOT/'src/makos/theme/decoration/contents/images'
    dest.mkdir(parents=True,exist_ok=True)
    palette={'close':(228,81,68),'minimize':(220,163,41),'zoom':(103,181,71)}
    for name,color in palette.items():
        for state in ('active','inactive','pressed'):
            for scale,size in (('',28),('@2x',56)):
                S=size*4  # supersample
                im=Image.new('RGBA',(S,S));d=ImageDraw.Draw(im)
                base=(176,182,190) if state=='inactive' else color
                if state=='pressed':base=tuple(round(v*.78) for v in base)
                c=S/2
                for step in range(int(S*.47),0,-1):
                    t=step/(S*.47)
                    # darker rim, light core near the lower-middle: reads as a glass bead
                    shade=tuple(min(255,round(v*(.72+.5*(1-t)**1.4))) for v in base)
                    d.ellipse((c-step,c-step,c+step,c+step),fill=shade+(255,))
                rim=max(2,S//28)
                d.ellipse((c-S*.47,c-S*.47,c+S*.47,c+S*.47),outline=tuple(round(v*.55) for v in base)+(255,),width=rim)
                hl=Image.new('RGBA',(S,S));hd=ImageDraw.Draw(hl)
                hd.ellipse((S*.2,S*.08,S*.8,S*.5),fill=(255,255,255,200 if state!='inactive' else 150))
                im=Image.alpha_composite(im,hl)
                im.resize((size,size),Image.Resampling.LANCZOS).save(dest/f'orb-{name}-{state}{scale}.png')
    for scale,size in (('',128),('@2x',256)):
        image=Image.new('L',(size,size))
        px=image.load()
        for y in range(size):
            for x in range(size):
                sx=x/size*2*math.pi;sy=y/size*2*math.pi
                px[x,y]=max(0,min(255,round(128+34*math.sin(sy*16)+20*math.sin(sy*26+sx)+9*math.sin(sx*2))))
        image.convert('RGBA').save(dest/f'metal{scale}.png')


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
    dock_shelves()  # dock-shelf-{flat,3d}{,-left,-mid,-right}.png
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
    decoration_images()
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
