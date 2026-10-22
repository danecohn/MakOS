#!/usr/bin/env python3
"""Qt (PyQt6) widget window for the rig: a menu bar, toolbar and the standard widgets.
  --mode main|tool|dialog   main window, utility palette, or modal dialog
  --hold SECONDS            quit after this long (the rig kills it by PID anyway)
The skin comes from the environment (QT_STYLE_OVERRIDE / QT_QPA_PLATFORMTHEME), like any Qt app."""
import argparse
import sys
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QCheckBox, QRadioButton,
                             QLineEdit, QSpinBox, QComboBox, QSlider, QProgressBar, QTabWidget, QListWidget, QTreeWidget, QTreeWidgetItem,
                             QGroupBox, QLabel, QTextEdit, QScrollBar, QDialog, QToolBar, QStatusBar, QDial, QFrame)

ap = argparse.ArgumentParser()
ap.add_argument('--mode', default='main')
ap.add_argument('--hold', type=float, default=60)
ap.add_argument('--title', default='Qt Widgets')
ap.add_argument('--menu-export', action='store_true')
args, rest = ap.parse_known_args()
app = QApplication([sys.argv[0]] + rest)


def widgets():
    root = QWidget()
    grid = QGridLayout(root)
    left = QVBoxLayout()
    row = QHBoxLayout()
    for text in ('Normal', 'Default', 'Disabled'):
        b = QPushButton(text)
        b.setEnabled(text != 'Disabled')
        b.setDefault(text == 'Default')
        row.addWidget(b)
    toggle = QPushButton('Toggle'); toggle.setCheckable(True); toggle.setChecked(True); row.addWidget(toggle)
    left.addLayout(row)
    for text, state in (('Checked', True), ('Unchecked', False)):
        c = QCheckBox(text); c.setChecked(state); left.addWidget(c)
    c = QCheckBox('Tristate'); c.setTristate(True); c.setCheckState(Qt.CheckState.PartiallyChecked); left.addWidget(c)
    r1 = QRadioButton('Radio A'); r1.setChecked(True); left.addWidget(r1); left.addWidget(QRadioButton('Radio B'))
    e = QLineEdit('Line edit'); left.addWidget(e)
    d = QLineEdit('Disabled'); d.setEnabled(False); left.addWidget(d)
    s = QSpinBox(); s.setValue(42); left.addWidget(s)
    cb = QComboBox(); cb.addItems(['Combo box', 'Second', 'Third']); left.addWidget(cb)
    sl = QSlider(Qt.Orientation.Horizontal); sl.setValue(40); left.addWidget(sl)
    p = QProgressBar(); p.setValue(62); left.addWidget(p)
    left.addStretch()
    mid = QVBoxLayout()
    tabs = QTabWidget()
    for t in ('General', 'Advanced', 'About'):
        page = QWidget(); lay = QVBoxLayout(page); lay.addWidget(QLabel(t + ' page')); lay.addWidget(QTextEdit('Text edit\nsecond line'))
        tabs.addTab(page, t)
    mid.addWidget(tabs)
    gb = QGroupBox('Group box'); gl = QVBoxLayout(gb); gl.addWidget(QLabel('Inside the group')); gl.addWidget(QDial()); mid.addWidget(gb)
    right = QVBoxLayout()
    lw = QListWidget(); lw.addItems(['Documents', 'Pictures', 'Music', 'Archive.zip', 'Report.txt']); lw.setCurrentRow(1); lw.setAlternatingRowColors(True); right.addWidget(lw)
    tw = QTreeWidget(); tw.setHeaderLabels(['Name', 'Kind']); tw.setAlternatingRowColors(True)
    for n, k in (('Documents', 'Folder'), ('Pictures', 'Folder'), ('Report.txt', 'Document'), ('Notes.md', 'Document')):
        tw.addTopLevelItem(QTreeWidgetItem([n, k]))
    tw.setCurrentItem(tw.topLevelItem(1)); right.addWidget(tw)
    grid.addLayout(left, 0, 0); grid.addLayout(mid, 0, 1); grid.addLayout(right, 0, 2)
    return root


if args.mode == 'main':
    win = QMainWindow()
    win.setWindowTitle(args.title)
    win.resize(980, 560)
    mb = win.menuBar()
    for name, items in (('File', ['New', 'Open…', 'Save', 'Quit']), ('Edit', ['Undo', 'Redo', 'Copy', 'Paste']), ('View', ['Zoom In', 'Zoom Out'])):
        m = mb.addMenu(name)
        for it in items:
            m.addAction(it)
    tb = QToolBar('Tools'); [tb.addAction(t) for t in ('Back', 'Forward', 'Reload')]; win.addToolBar(tb)
    win.setCentralWidget(widgets())
    win.setStatusBar(QStatusBar()); win.statusBar().showMessage('Ready')
    win.show()
elif args.mode == 'tool':
    win = QWidget(None, Qt.WindowType.Tool)
    win.setWindowTitle('Inspector')
    lay = QVBoxLayout(win); lay.addWidget(QLabel('Tool palette')); lay.addWidget(QSlider(Qt.Orientation.Horizontal)); lay.addWidget(QPushButton('Action'))
    win.resize(260, 160)
    win.show()
else:
    parent = QMainWindow(); parent.setWindowTitle('Parent'); parent.resize(500, 300); parent.show()
    win = QDialog(parent)
    win.setWindowTitle('Save changes?')
    win.setModal(True)
    lay = QVBoxLayout(win); lay.addWidget(QLabel('Your changes will be lost if you do not save.'))
    row = QHBoxLayout(); b1 = QPushButton('Cancel'); b2 = QPushButton('Save'); b2.setDefault(True); row.addStretch(); row.addWidget(b1); row.addWidget(b2); lay.addLayout(row)
    win.show()
QTimer.singleShot(int(args.hold * 1000), app.quit)
sys.exit(app.exec())
