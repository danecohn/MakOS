#!/usr/bin/env python3
"""Original compact vector assets for the development preview (not AI icon substitutes).

Colours are drawn in the original blue-grey and remapped to the VigilTech rose/plum palette by vigil() below."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import colorsys
import re


def vigil(text):
    """Remap blue and blue-grey hex colours to VigilTech rose (saturated) and plum-grey (neutral)."""
    def one(m):
        h=m.group(1)
        if len(h)==3:h=''.join(c*2 for c in h)
        r,g,b=(int(h[i:i+2],16)/255 for i in (0,2,4))
        hue,light,sat=colorsys.rgb_to_hls(r,g,b)
        deg=hue*360
        if 150<=deg<=265 and sat>0.04:
            if sat>0.35:hue,sat=340/360,min(1,sat+.15)
            else:hue,sat=318/360,sat*.7
            r,g,b=colorsys.hls_to_rgb(hue,light,sat)
            return '#%02x%02x%02x'%(round(r*255),round(g*255),round(b*255))
        return m.group(0)
    return re.sub(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b',one,text)
OUT=ROOT/'src/makos/icons/MakkOS/scalable/apps'
DEFS='''<defs><linearGradient id="blue" x2=".2" y2="1"><stop stop-color="#c6edff"/><stop offset=".48" stop-color="#62b4ed"/><stop offset=".5" stop-color="#3182c3"/><stop offset="1" stop-color="#80c2ef"/></linearGradient><linearGradient id="silver" x2="0" y2="1"><stop stop-color="#fff"/><stop offset=".5" stop-color="#e2e8ed"/><stop offset="1" stop-color="#9dabb9"/></linearGradient><linearGradient id="paper" x2="0" y2="1"><stop stop-color="#fffef5"/><stop offset="1" stop-color="#e0e5e5"/></linearGradient></defs>'''
FOLDER='<path d="M8 22 Q8 17 13 17 H26 L32 23 H55 Q59 23 59 28 L55 53 H9Z" fill="url(#blue)" stroke="#3675a4"/><path d="M10 31 H57 L53 53 H10Z" fill="#72b7e4" opacity=".7"/><path d="M10 30 H57" stroke="white" opacity=".8"/>'
PAGE='<path d="M16 7 H41 L51 18 V56 H16Z" fill="url(#paper)" stroke="#8a9cad"/><path d="M41 7 V18 H51" fill="#b5d1ea" stroke="#8a9cad"/>'
DRIVE='<path d="M14 16 H50 L58 49 Q58 55 52 55 H12 Q6 55 6 49Z" fill="url(#silver)" stroke="#7f8e9c"/><rect x="10" y="44" width="44" height="7" rx="3" fill="#a5b0bd"/><circle cx="48" cy="48" r="2" fill="#6fb657"/>'
MOTIFS={
'seek':'<circle cx="27" cy="25" r="16" fill="#c4e8fa" fill-opacity=".5" stroke="#6a839b" stroke-width="5"/><path d="M39 38 L55 55" stroke="#4d789e" stroke-width="9" stroke-linecap="round"/>',
'calculator':'<rect x="14" y="7" width="36" height="50" rx="6" fill="url(#silver)" stroke="#748aa0"/><rect x="19" y="13" width="26" height="12" rx="2" fill="#44677e"/>'+''.join(f'<rect x="{19+x*10}" y="{31+y*9}" width="6" height="5" rx="1" fill="#6294c0"/>' for x in range(3) for y in range(3)),
'clock':'<circle cx="32" cy="32" r="25" fill="url(#silver)" stroke="#7e9db5"/><circle cx="32" cy="32" r="21" fill="#f4f9fc"/><path d="M32 16 V32 L44 38" stroke="#39566f" stroke-width="3" fill="none" stroke-linecap="round"/>',
'calendar':'<rect x="9" y="12" width="46" height="45" rx="4" fill="url(#paper)" stroke="#8ea5b7"/><path d="M9 25 V16 Q9 12 13 12 H51 Q55 12 55 16 V25Z" fill="url(#blue)"/><path d="M21 7 V18 M43 7 V18" stroke="#577e9b" stroke-width="4" stroke-linecap="round"/>'+''.join(f'<rect x="{17+x*12}" y="{32+y*10}" width="6" height="4" fill="#86a5bc"/>' for x in range(3) for y in range(2)),
'activity':'<rect x="7" y="14" width="50" height="38" rx="4" fill="#27445c" stroke="#9cb2c5" stroke-width="3"/><path d="M11 36 H20 L25 23 L32 44 L39 28 L45 36 H53" fill="none" stroke="#82e4eb" stroke-width="3"/>',
'preview':'<rect x="8" y="12" width="45" height="39" rx="3" fill="url(#silver)" stroke="#7f9aae"/><rect x="12" y="16" width="37" height="31" fill="#8bc5e8"/><path d="M12 47 L27 28 L38 41 L42 35 L49 47Z" fill="#68969d"/><circle cx="40" cy="23" r="4" fill="#fff0b0"/>',
'contacts':'<rect x="12" y="8" width="39" height="49" rx="4" fill="url(#blue)" stroke="#39789f"/><circle cx="32" cy="25" r="8" fill="#e9f5fa"/><path d="M20 47 Q20 34 32 34 Q44 34 44 47Z" fill="#e9f5fa"/>',
'music':'<path d="M25 18 V47 M48 11 V39 M25 18 L48 11" fill="none" stroke="#438dc0" stroke-width="7"/><ellipse cx="18" cy="48" rx="10" ry="7" fill="url(#blue)"/><ellipse cx="41" cy="40" rx="10" ry="7" fill="url(#blue)"/>',
'video':'<rect x="7" y="13" width="50" height="39" rx="5" fill="url(#silver)" stroke="#7b90a5"/><rect x="11" y="17" width="42" height="31" rx="2" fill="#31556e"/><path d="M27 24 L42 33 L27 42Z" fill="#c4eafa"/>',
'desktops':'<rect x="7" y="9" width="50" height="35" rx="3" fill="url(#silver)" stroke="#758b9f"/><rect x="11" y="13" width="42" height="27" fill="#7fc3e9"/><path d="M32 44 V53 M20 55 H44" stroke="#9aacbb" stroke-width="5"/>',
'spread':'<rect x="8" y="9" width="21" height="19" rx="3" fill="url(#blue)"/><rect x="35" y="9" width="21" height="19" rx="3" fill="url(#silver)"/><rect x="8" y="34" width="21" height="19" rx="3" fill="url(#silver)"/><rect x="35" y="34" width="21" height="19" rx="3" fill="url(#blue)"/>',
'widgets':'<rect x="9" y="9" width="46" height="46" rx="11" fill="url(#silver)" stroke="#809ab2"/>'+''.join(f'<circle cx="{x}" cy="{y}" r="6" fill="url(#blue)"/>' for x in (23,41) for y in (23,41)),
'rewind':'<path d="M14 22 A23 23 0 1 1 12 42" fill="none" stroke="#6d98bc" stroke-width="8"/><path d="M7 11 L7 29 L26 29" fill="none" stroke="#6d98bc" stroke-width="7" stroke-linejoin="round"/><path d="M33 18 V33 L44 40" fill="none" stroke="#4d738f" stroke-width="3"/>',
'chatgpt':'<path d="M10 13 Q10 7 16 7 H48 Q55 7 55 14 V44 Q55 50 48 50 H29 L16 59 V50 Q10 50 10 44Z" fill="url(#blue)" stroke="#517b9d"/><path d="M21 24 H45 M21 32 H41" stroke="#f2fbff" stroke-width="3"/>',
'claude':'<path d="M10 14 Q10 8 16 8 H48 Q54 8 54 14 V43 Q54 49 48 49 H35 L47 59 H21 Q10 59 10 49Z" fill="url(#silver)" stroke="#8095a9"/><path d="M21 24 H44 M21 32 H38" stroke="#5486ad" stroke-width="3"/>',
'makos-logo': (ROOT/'src/makos/branding/vigilos.svg').read_text().split('</title>',1)[1].rsplit('</svg>',1)[0].replace('width="256" height="256"','width="64" height="64"'),
}

# ---- Settings pane icons (settings-and-Seek engineer). One distinct original geometric drawing per pane.
# These are development FALLBACKS: each is marked in the SVG and in docs/makos/settings.md for AI regeneration.
PANE_MOTIFS={
'appearance':'<circle cx="32" cy="32" r="23" fill="url(#silver)" stroke="#7c93a8"/><path d="M32 9 A23 23 0 0 1 32 55Z" fill="url(#blue)"/><circle cx="32" cy="32" r="8" fill="#fff" stroke="#7c93a8"/>',
'desktop':'<rect x="6" y="10" width="52" height="34" rx="3" fill="url(#silver)" stroke="#758b9f"/><path d="M10 40 L24 24 L33 33 L40 26 L54 40Z" fill="#5f9bc4"/><circle cx="44" cy="19" r="4" fill="#fff0b0"/><path d="M22 54 H42 M32 44 V54" stroke="#8fa3b5" stroke-width="4" stroke-linecap="round"/>',
'launcher':'<rect x="5" y="36" width="54" height="18" rx="6" fill="url(#silver)" stroke="#7d93a8"/>'+''.join(f'<rect x="{10+i*13}" y="{(40 if i not in (1,2) else 26)-(0 if i!=2 else 6)}" width="{9 if i not in (1,2) else 12 }" height="{9 if i not in (1,2) else 12}" rx="3" fill="url(#blue)" stroke="#3e7fb0"/>' for i in range(4)),
'desks':'<rect x="5" y="14" width="25" height="20" rx="3" fill="url(#blue)" stroke="#3e7fb0"/><rect x="34" y="14" width="25" height="20" rx="3" fill="url(#silver)" stroke="#7d93a8"/><rect x="5" y="38" width="25" height="14" rx="3" fill="url(#silver)" stroke="#7d93a8"/><rect x="34" y="38" width="25" height="14" rx="3" fill="url(#silver)" stroke="#7d93a8"/><path d="M5 8 H15 M59 8 H49" stroke="#4d789e" stroke-width="3" stroke-linecap="round"/>',
'language':'<rect x="6" y="9" width="35" height="30" rx="5" fill="url(#blue)" stroke="#3e7fb0"/><path d="M14 18 H33 M23.5 14 V18 M17 30 Q24 26 31 18 M19 22 Q24 29 31 31" fill="none" stroke="#fff" stroke-width="2.4"/><rect x="26" y="29" width="32" height="26" rx="5" fill="url(#paper)" stroke="#8aa0b3"/><path d="M34 49 L42 33 L50 49 M37 44 H47" fill="none" stroke="#4d738f" stroke-width="3"/>',
'security':'<path d="M32 6 L54 14 V32 Q54 48 32 58 Q10 48 10 32 V14Z" fill="url(#silver)" stroke="#6f879c" stroke-width="1.5"/><rect x="22" y="29" width="20" height="16" rx="3" fill="url(#blue)" stroke="#3e7fb0"/><path d="M26 29 V24 Q26 17 32 17 Q38 17 38 24 V29" fill="none" stroke="#4d789e" stroke-width="3"/>',
'displays':'<rect x="5" y="9" width="40" height="29" rx="3" fill="url(#silver)" stroke="#758b9f"/><rect x="9" y="13" width="32" height="21" fill="#7fc3e9"/><rect x="38" y="24" width="21" height="26" rx="3" fill="url(#silver)" stroke="#758b9f"/><rect x="41" y="27" width="15" height="20" fill="#9bd0ea"/><path d="M18 38 V46 M10 48 H28" stroke="#9aacbb" stroke-width="4" stroke-linecap="round"/>',
'keyboard':'<rect x="4" y="18" width="56" height="30" rx="5" fill="url(#silver)" stroke="#758b9f"/>'+''.join(f'<rect x="{9+c*8.4}" y="{22+r*8}" width="6" height="5" rx="1.2" fill="#6294c0"/>' for r in range(2) for c in range(6))+'<rect x="16" y="39" width="32" height="5" rx="1.5" fill="#6294c0"/>',
'mouse':'<path d="M32 6 C46 6 52 16 52 30 V38 C52 50 44 58 32 58 C20 58 12 50 12 38 V30 C12 16 18 6 32 6Z" fill="url(#silver)" stroke="#758b9f" stroke-width="1.5"/><path d="M32 7 V28 M13 28 H51" stroke="#8fa3b5" stroke-width="2"/><rect x="29" y="14" width="6" height="11" rx="3" fill="url(#blue)"/>',
'sound':'<path d="M8 25 H18 L32 13 V51 L18 39 H8Z" fill="url(#silver)" stroke="#758b9f" stroke-linejoin="round"/><path d="M39 22 Q46 32 39 42 M45 15 Q58 32 45 49" fill="none" stroke="#4d8fc4" stroke-width="4" stroke-linecap="round"/>',
'energy':'<rect x="7" y="19" width="43" height="27" rx="5" fill="url(#silver)" stroke="#758b9f"/><rect x="50" y="27" width="6" height="11" rx="2" fill="#8fa3b5"/><path d="M31 22 L21 34 H29 L25 44 L38 30 H30Z" fill="#6fb657" stroke="#3f7f31"/>',
'printers':'<rect x="16" y="6" width="32" height="18" fill="url(#paper)" stroke="#8aa0b3"/><rect x="6" y="22" width="52" height="25" rx="5" fill="url(#silver)" stroke="#758b9f"/><rect x="16" y="38" width="32" height="19" fill="url(#paper)" stroke="#8aa0b3"/><path d="M21 44 H43 M21 50 H38" stroke="#8ca7bd" stroke-width="2"/><circle cx="49" cy="29" r="2.5" fill="#6fb657"/>',
'bluetooth':'<circle cx="32" cy="32" r="25" fill="url(#blue)" stroke="#3e7fb0"/><path d="M22 23 L42 41 L32 50 V14 L42 23 L22 41" fill="none" stroke="#fff" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>',
'network':'<circle cx="32" cy="32" r="24" fill="url(#blue)" stroke="#3e7fb0"/><path d="M12 25 H52 M10 38 H54" stroke="#cceaff" stroke-width="2"/><ellipse cx="32" cy="32" rx="10" ry="24" fill="none" stroke="#cceaff" stroke-width="2"/><path d="M32 8 V56" stroke="#cceaff" stroke-width="2"/><circle cx="50" cy="50" r="7" fill="#fff" stroke="#3e7fb0"/><path d="M46 50 H54 M50 46 V54" stroke="#3e7fb0" stroke-width="2"/>',
'sharing':'<circle cx="18" cy="32" r="8" fill="url(#blue)" stroke="#3e7fb0"/><circle cx="46" cy="16" r="8" fill="url(#silver)" stroke="#758b9f"/><circle cx="46" cy="48" r="8" fill="url(#silver)" stroke="#758b9f"/><path d="M25 28 L39 19 M25 36 L39 45" stroke="#4d789e" stroke-width="3"/>',
'users':'<circle cx="32" cy="22" r="11" fill="url(#blue)" stroke="#3e7fb0"/><path d="M10 56 Q10 36 32 36 Q54 36 54 56Z" fill="url(#silver)" stroke="#758b9f"/>',
'datetime':'<rect x="7" y="9" width="40" height="40" rx="4" fill="url(#paper)" stroke="#8ea5b7"/><path d="M7 20 V13 Q7 9 11 9 H43 Q47 9 47 13 V20Z" fill="url(#blue)"/><circle cx="44" cy="44" r="15" fill="url(#silver)" stroke="#6f879c"/><circle cx="44" cy="44" r="11.5" fill="#f4f9fc"/><path d="M44 36 V44 L50 47" stroke="#39566f" stroke-width="2.5" fill="none" stroke-linecap="round"/>',
'update':'<circle cx="32" cy="32" r="24" fill="url(#silver)" stroke="#7a91a6"/><path d="M32 14 V37 M22 28 L32 38 L42 28" fill="none" stroke="#3e7fb0" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M18 46 H46" stroke="#3e7fb0" stroke-width="5" stroke-linecap="round"/>',
'accessibility':'<circle cx="32" cy="32" r="25" fill="url(#blue)" stroke="#3e7fb0"/><circle cx="32" cy="17" r="4.5" fill="#fff"/><path d="M15 25 Q32 30 49 25 M32 28 V40 M32 40 L24 53 M32 40 L40 53" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>',
'startup':'<circle cx="32" cy="34" r="22" fill="url(#silver)" stroke="#758b9f"/><path d="M32 8 V32" stroke="#3e7fb0" stroke-width="6" stroke-linecap="round"/><path d="M20 18 A20 20 0 1 0 44 18" fill="none" stroke="#3e7fb0" stroke-width="5" stroke-linecap="round"/>',
'rewind':MOTIFS['rewind'],
}
PANE_NAMES=['pane-'+k for k in PANE_MOTIFS]
FALLBACK_NOTE='<!-- FALLBACK: original vector placeholder for the Settings pane icon; regenerate with the AI image pipeline (see docs/makos/settings.md) -->'

# ---- Application icons for the Studio suite (core-apps engineer): development fallbacks, one distinct drawing each.
import math as _m
_GEAR=''.join(f'<rect x="28" y="6" width="8" height="12" rx="2" fill="url(#silver)" stroke="#7a91a6" transform="rotate({a} 32 32)"/>' for a in range(0,360,45))
APP_MOTIFS={
'makbox':'<rect x="9" y="12" width="46" height="42" rx="8" fill="url(#silver)" stroke="#758b9f"/><circle cx="32" cy="38" r="12" fill="url(#blue)" stroke="#3e7fb0"/><circle cx="32" cy="38" r="4" fill="#e9f5fa"/><circle cx="32" cy="21" r="3.5" fill="#8fa3b5"/><path d="M16 20 H24 M40 20 H48" stroke="#8fa3b5" stroke-width="3" stroke-linecap="round"/>',
'render':'<path d="M32 6 L55 18 V44 L32 58 L9 44 V18Z" fill="url(#blue)" stroke="#3a76a6" stroke-linejoin="round"/><path d="M32 32 L55 18 M32 32 L9 18 M32 32 V58" stroke="#e5f5ff" stroke-width="2" fill="none"/><path d="M32 6 L55 18 L32 32 L9 18Z" fill="#d6eefc" opacity=".55"/>',
'engine':_GEAR+'<circle cx="32" cy="32" r="20" fill="url(#silver)" stroke="#7a91a6"/><circle cx="32" cy="32" r="11" fill="url(#blue)" stroke="#3e7fb0"/><path d="M29 26 L38 32 L29 38Z" fill="#fff"/>',
'sprite':''.join(f'<rect x="{11+x*6}" y="{11+y*6}" width="6" height="6" fill="{c}"/>' for y,row in enumerate(['bbbbbbb','bcwwwwb','bcwwwwb','.bwwwb.','..bwwb.','...bb..','...b...']) for x,ch in enumerate(row) for c in [{'b':'#3e7fb0','w':'#bfe3fa','c':'#ffffff'}.get(ch)] if c),
'studio':'<path d="M32 5 L56 19 V45 L32 59 L8 45 V19Z" fill="url(#silver)" stroke="#758b9f" stroke-linejoin="round"/><rect x="17" y="21" width="13" height="13" rx="2" fill="url(#blue)"/><rect x="34" y="21" width="13" height="13" rx="2" fill="#a9c9e2"/><rect x="17" y="38" width="13" height="8" rx="2" fill="#a9c9e2"/><circle cx="41" cy="42" r="6" fill="url(#blue)"/>',
}
APP_ICON_NAMES=list(APP_MOTIFS)

def svg(body):
    return vigil('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'+DEFS+body+'</svg>')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    import importlib.util
    spec=importlib.util.spec_from_file_location('ingest',ROOT/'tools/ingest_makos_assets.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in module.NAMES+['chatgpt','claude','makos-logo']:
        if name in MOTIFS:
            body=MOTIFS[name]
        elif name.startswith('folder') or name=='files':
            body=FOLDER
        elif name.startswith('drive') or name=='disk-utility':
            body=DRIVE
        elif name.startswith('file') or name in ('text-editor','notes','mail','dictionary'):
            body=PAGE+'<path d="M22 28 H44 M22 35 H44 M22 42 H38" stroke="#8ca7bd" stroke-width="2"/>'
        elif name in ('photos','screenshot','maps'):
            body=MOTIFS['preview']
        elif name in ('software-center','app-store','settings','system-info'):
            body=MOTIFS['widgets']
        elif name.startswith('trash'):
            body='<path d="M15 20 H49 L45 56 H19Z" fill="url(#silver)" stroke="#809aaf"/><ellipse cx="32" cy="20" rx="18" ry="5" fill="#b9d0df" stroke="#809aaf"/>'
        elif name=='terminal':
            body='<rect x="7" y="12" width="50" height="40" rx="5" fill="#213e55" stroke="#b8c9d6" stroke-width="3"/><path d="M17 24 L25 31 L17 38 M31 39 H43" stroke="#9ad7f1" stroke-width="3" fill="none"/>'
        elif name=='browser':
            body='<circle cx="32" cy="32" r="24" fill="url(#blue)" stroke="#6096bd"/><ellipse cx="32" cy="32" rx="11" ry="24" fill="none" stroke="#cceaff" stroke-width="2"/><path d="M9 32 H55" stroke="#cceaff" stroke-width="2"/>'
        else:
            body=MOTIFS['video']
        (OUT/f'makos-{name}.svg').write_text(svg(body))
    for key,body in PANE_MOTIFS.items():
        (OUT/f'makos-pane-{key}.svg').write_text(svg(body).replace('<defs>',FALLBACK_NOTE+'<defs>',1))
    for key,body in APP_MOTIFS.items():
        (OUT/f'makos-{key}.svg').write_text(svg(body).replace('<defs>',FALLBACK_NOTE.replace('Settings pane','application').replace('docs/makos/settings.md','docs/makos/ICON-REQUESTS.md')+'<defs>',1))
    print('Original development vector set:',len(list(OUT.glob('*.svg'))))
if __name__=='__main__':main()
