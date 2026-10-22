#!/usr/bin/env python3
"""Original compact vector assets for the development preview (not AI icon substitutes)."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'src/makos/icons/MakOS/scalable/apps'
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
'makos-logo':'<path d="M7 49 V15 L20 8 L32 31 L44 8 L57 15 V49 L44 56 V29 L32 48 L20 29 V56Z" fill="url(#blue)" stroke="#326e9a" stroke-width="1.5"/>',
}

def svg(body):
    return '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'+DEFS+body+'</svg>'

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
    print('Original development vector set:',len(list(OUT.glob('*.svg'))))
if __name__=='__main__':main()
