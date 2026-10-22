"""Prompt-template helpers shared by the Studio apps (Python side; the JS apps carry the same text in ai-client.js users)."""
import json
import re

BASE = (
    'You are the built-in assistant of {title}, part of Studio on MakOS. The user describes what they want '
    'and you build it by calling the tools you are given. Prefer small, verifiable steps; inspect before you change; '
    'after changing something, check the result with a read tool when one exists. Never invent tool names. Work only '
    'inside the open project. If a request is ambiguous, make a sensible choice and say what you chose. Keep replies '
    'short and concrete.')

APP_NOTES = {
    'render': 'You drive Blender 5.x through its Python API (bpy). Units are metres. Name objects meaningfully, keep '
              'geometry clean, apply materials with the Principled BSDF. When you must run Python, send complete, '
              'idempotent snippets and never import network or process modules.',
    'engine': 'You build Godot 4 projects. Use typed GDScript, small scenes, signals for communication and the '
              "project's recipes for common genres. Paths are res://-relative inside the project.",
    'sprite': 'You make pixel art. Respect the canvas size and palette, use hard pixel edges (no anti-aliasing), keep '
              'silhouettes readable at 1x. Frames are animation frames.',
    'box': 'You compose chiptune music as BeepBox song JSON. Keep the song valid: the format version, key, scale, '
           'tempo, channel/pattern/sequence structure of BeepBox. Prefer 4/4 and loopable arrangements.',
}


def system_prompt(app, title=None, project_summary=None, extra=None):
    from .common import APP_TITLES
    parts = [BASE.format(title=title or APP_TITLES.get(app, 'Studio')), APP_NOTES.get(app, '')]
    if project_summary:
        parts.append('Current project:\n' + project_summary)
    if extra:
        parts.append(extra)
    return '\n\n'.join(p for p in parts if p)


def user_request(text, context=None):
    """The user's instruction, optionally followed by structured context the app collected (selection, canvas info...)."""
    if not context:
        return text
    return f'{text}\n\n<context>\n{json.dumps(context, ensure_ascii=False, indent=1)}\n</context>'


_FENCE = re.compile(r'```(?:[a-zA-Z0-9_+-]*)\n(.*?)```', re.S)


def extract_code(text, lang=None):
    """The first fenced code block of a model answer (or the whole text when there is none)."""
    if lang:
        m = re.search(r'```' + re.escape(lang) + r'\n(.*?)```', text, re.S)
        if m:
            return m.group(1).strip()
    m = _FENCE.search(text)
    return (m.group(1) if m else text).strip()


def extract_json(text):
    """Parse the first JSON object/array in a model answer (fenced or bare). Raises ValueError when there is none."""
    candidates = [extract_code(text)] if '```' in text else []
    candidates.append(text)
    for cand in candidates:
        cand = cand.strip()
        for opener, closer in (('{', '}'), ('[', ']')):
            i, j = cand.find(opener), cand.rfind(closer)
            if i != -1 and j > i:
                try:
                    return json.loads(cand[i:j + 1])
                except ValueError:
                    continue
    raise ValueError('no JSON found in the answer')
