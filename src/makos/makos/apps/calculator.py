"""Calculator: basic, scientific and programmer modes over a bounded AST evaluator (never eval)."""
import ast
import math
import operator
import re
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
from .. import ui
from .base import AppWindow

MAX_LEN, MAX_NODES = 200, 140
CONSTANTS = {'pi': math.pi, 'e': math.e, 'tau': math.tau}


def _fact(n):
    if n != int(n) or n < 0 or n > 170:
        raise ValueError('Factorial needs an integer from 0 to 170')
    return float(math.factorial(int(n)))


def _checked(fn):
    def call(*args):
        try:
            return fn(*args)
        except (ValueError, OverflowError) as error:
            raise ValueError('Math domain error') from error
    return call


FUNCS = {n: _checked(getattr(math, n)) for n in ('sinh', 'cosh', 'tanh', 'sqrt', 'floor', 'ceil', 'exp', 'log2', 'degrees', 'radians')}
FUNCS.update({'abs': abs, 'fact': _fact, 'ln': _checked(math.log), 'log': _checked(math.log10), 'cbrt': lambda x: math.copysign(abs(x) ** (1 / 3), x),
              'pow': lambda a, b: _pow(a, b), 'mod': _checked(math.fmod), 'round': lambda x, n=0: round(x, int(n))})
TRIG = ('sin', 'cos', 'tan')
ARC = ('asin', 'acos', 'atan')
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
BITS = {ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor, ast.LShift: operator.lshift, ast.RShift: operator.rshift}


def _pow(a, b):
    if abs(b) > 400 or (abs(a) > 1e8 and abs(b) > 30):
        raise ValueError('Power too large')
    return a ** b


def normalize(text, mode):
    text = text.strip().replace('×', '*').replace('÷', '/').replace('−', '-').replace('π', 'pi').replace('√', 'sqrt').replace(',', '.')
    if mode != 'programmer':
        text = text.replace('^', '**')
    text = re.sub(r'(\d+(?:\.\d+)?|\([^()]*\))!', r'fact(\1)', text)
    text = re.sub(r'(\d+(?:\.\d+)?)%', r'(\1/100)', text)
    return text


def evaluate(text, mode='basic', degrees=False, bits=64, ans=0):
    """Return a number (int in programmer mode). Raises ValueError for anything not plain arithmetic."""
    text = normalize(text, mode)
    if not text or len(text) > MAX_LEN:
        raise ValueError('Enter a calculation')
    tree = ast.parse(text, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ValueError('Expression too complex')
    programmer = mode == 'programmer'
    mask = (1 << bits) - 1

    def num(n):
        if isinstance(n, ast.Constant) and type(n.value) in ((int,) if programmer else (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id == 'ans':
                return ans
            if not programmer and n.id in CONSTANTS:
                return CONSTANTS[n.id]
            raise ValueError(f'Unknown name {n.id}')
        if isinstance(n, ast.UnaryOp):
            v = num(n.operand)
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return v
            if isinstance(n.op, ast.Invert) and programmer:
                return ~v & mask
            raise ValueError('Unsupported operator')
        if isinstance(n, ast.BinOp):
            op = type(n.op)
            a, b = num(n.left), num(n.right)
            if op in BIN:
                if op in (ast.Div, ast.FloorDiv, ast.Mod) and b == 0:
                    raise ZeroDivisionError('Division by zero')
                v = BIN[op](a, b)
                return int(v) if programmer and op is ast.Div else v
            if op is ast.Pow and not programmer:
                return _pow(a, b)
            if op in BITS and programmer:
                if op in (ast.LShift, ast.RShift) and not 0 <= b <= 128:
                    raise ValueError('Shift out of range')
                return BITS[op](a, b) & mask if op is not ast.RShift else (a & mask) >> b
            raise ValueError('Unsupported operator')
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords and not programmer:
            name, args = n.func.id, [num(a) for a in n.args]
            if name in TRIG:
                return getattr(math, name)(math.radians(args[0]) if degrees else args[0])
            if name in ARC:
                try:
                    v = getattr(math, name)(*args)
                except ValueError as error:
                    raise ValueError('Math domain error') from error
                return math.degrees(v) if degrees else v
            if name in FUNCS and 1 <= len(args) <= 2:
                return FUNCS[name](*args)
        raise ValueError('Use numbers, arithmetic and listed functions')

    value = num(tree.body)
    if isinstance(value, complex) or (isinstance(value, float) and not math.isfinite(value)) or abs(value) > 1e300:
        raise ValueError('Result out of range')
    return value & mask if programmer else value


def format_value(value, base=10, bits=64):
    if isinstance(value, int) and not isinstance(value, bool):
        if base == 16:
            return format(value & ((1 << bits) - 1), 'X')
        if base == 8:
            return format(value & ((1 << bits) - 1), 'o')
        if base == 2:
            return format(value & ((1 << bits) - 1), 'b')
        return str(value)
    text = format(value, '.12g')
    return '0' if text in ('-0',) else text


def signed(value, bits):
    return value - (1 << bits) if value >> (bits - 1) else value


BASIC_KEYS = [['C', '(', ')', '÷'], ['7', '8', '9', '×'], ['4', '5', '6', '−'], ['1', '2', '3', '+'], ['0', '.', '⌫', '=']]
SCI_KEYS = [['sin(', 'cos(', 'tan(', 'ln(', 'log('], ['asin(', 'acos(', 'atan(', 'sqrt(', 'exp('], ['pi', 'e', '^', '!', '%'], ['abs(', 'cbrt(', 'fact(', 'ans', 'Deg/Rad']]
PROG_KEYS = [['AND', 'OR', 'XOR', 'NOT'], ['<<', '>>', '(', ')'], ['D', 'E', 'F', 'C'], ['A', 'B', '0x', '⌫']]
MENU = [('File', [('Copy Result', 'copy', '<Primary>c'), ('Clear History', 'clear_history', None), None, ('Close', 'close', '<Primary>w')]),
        ('Edit', [('Clear', 'clear', 'Escape'), ('Memory Clear', 'mc', None), ('Memory Recall', 'mr', None), ('Add to Memory', 'mplus', None)]),
        ('View', [('Basic', 'mode_basic', '<Primary>1'), ('Scientific', 'mode_scientific', '<Primary>2'), ('Programmer', 'mode_programmer', '<Primary>3')])]


class Calculator:
    def __init__(self, app):
        self.mode, self.degrees, self.ans, self.memory, self.base, self.bits = 'basic', False, 0, 0, 10, 64
        self.history = []
        self.aw = AppWindow(app, 'Calculator', 360, 520, MENU, status=True)
        self.win = self.aw.win
        for name, fn in (('copy', self.copy), ('clear_history', self.clear_history), ('close', self.win.close), ('clear', self.clear),
                         ('mc', lambda: setattr(self, 'memory', 0)), ('mr', self.recall), ('mplus', self.mplus),
                         ('mode_basic', lambda: self.set_mode('basic')), ('mode_scientific', lambda: self.set_mode('scientific')),
                         ('mode_programmer', lambda: self.set_mode('programmer'))):
            self.aw.action(name, fn)
        col = ui.box(True, 8, 'sheet')
        self.expression = Gtk.Entry(hexpand=True, placeholder_text='Type or tap a calculation', css_classes=['calc-expression'])
        self.expression.connect('activate', lambda *_: self.compute())
        self.result = Gtk.Label(label='0', xalign=1, selectable=True, css_classes=['calc-display'])
        self.bases = Gtk.Label(label='', xalign=1, css_classes=['hint'], selectable=True)
        self.history_label = Gtk.Label(label='', xalign=1, css_classes=['hint'], wrap=True, max_width_chars=40)
        for w in (self.expression, self.result, self.bases):
            col.append(w)
        self.pad = ui.box(True, 5)
        col.append(self.pad)
        col.append(self.history_label)
        self.aw.body.append(col)
        self.set_mode('basic')

    def set_mode(self, mode):
        self.mode = mode
        ui.clear(self.pad)
        self.bases.set_visible(mode == 'programmer')
        layouts = {'basic': BASIC_KEYS, 'scientific': SCI_KEYS + BASIC_KEYS, 'programmer': PROG_KEYS + BASIC_KEYS}[mode]
        for row in layouts:
            line = ui.box(spacing=5)
            line.set_homogeneous(True)
            for key in row:
                label = key
                b = Gtk.Button(label=(('Deg' if self.degrees else 'Rad') if key == 'Deg/Rad' else label), css_classes=['calc-key'])
                if key in '÷×−+AND OR XOR NOT<< >>':
                    b.add_css_class('op')
                if key == '=':
                    b.add_css_class('suggested-action')
                    b.add_css_class('eq')
                b.connect('clicked', lambda btn, k=key: self.press(k, btn))
                line.append(b)
            self.pad.append(line)
        if mode == 'programmer':
            line = ui.box(spacing=5)
            line.set_homogeneous(True)
            for base, name in ((16, 'HEX'), (10, 'DEC'), (8, 'OCT'), (2, 'BIN')):
                line.append(ui.button(name, lambda b=base: self.set_base(b)))
            self.pad.append(line)
        self.aw.say({'basic': 'Basic', 'scientific': 'Scientific (' + ('degrees' if self.degrees else 'radians') + ')', 'programmer': f'Programmer, {self.bits}-bit'}[mode])

    def press(self, key, button=None):
        if key == 'C':
            self.clear()
        elif key == '⌫':
            self.expression.set_text(self.expression.get_text()[:-1])
        elif key == '=':
            self.compute()
        elif key == 'Deg/Rad':
            self.degrees = not self.degrees
            self.set_mode(self.mode)
        else:
            key = {'AND': ' & ', 'OR': ' | ', 'XOR': ' ^ ', 'NOT': '~', '<<': ' << ', '>>': ' >> '}.get(key, key)
            self.expression.set_text(self.expression.get_text() + key)
        self.expression.set_position(-1)

    def clear(self):
        self.expression.set_text('')
        self.result.set_text('0')
        self.bases.set_text('')

    def compute(self):
        text = self.expression.get_text()
        try:
            value = evaluate(text, self.mode, self.degrees, self.bits, self.ans)
        except ZeroDivisionError:
            self.result.set_text('Cannot divide by zero')
            return None
        except (ValueError, SyntaxError, OverflowError, TypeError):
            self.result.set_text('Check the expression')
            return None
        self.ans = value
        shown = format_value(value, self.base, self.bits)
        self.result.set_text(shown)
        if self.mode == 'programmer':
            self.bases.set_text('HEX %s   DEC %d   OCT %s   BIN %s' % (format_value(value, 16, self.bits), signed(value, self.bits), format_value(value, 8, self.bits), format_value(value, 2, self.bits)))
        self.history.append((text, shown))
        self.history_label.set_text('\n'.join(f'{a} = {b}' for a, b in self.history[-3:]))
        return shown

    def set_base(self, base):
        self.base = base
        if isinstance(self.ans, int):
            self.result.set_text(format_value(self.ans, base, self.bits))

    def copy(self):
        Gdk.Display.get_default().get_clipboard().set(self.result.get_text())

    def clear_history(self):
        self.history.clear()
        self.history_label.set_text('')

    def recall(self):
        self.expression.set_text(self.expression.get_text() + format_value(self.memory))

    def mplus(self):
        try:
            self.memory = float(self.result.get_text())
        except ValueError:
            pass


def open_window(app, path=None):
    calc = Calculator(app)
    calc.aw.present()
    return calc
