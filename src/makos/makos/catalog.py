"""A single visible entry per role. Backend executables keep their upstream identities."""
from dataclasses import dataclass

@dataclass(frozen=True)
class App:
    id: str
    name: str
    icon: str
    command: tuple = ()
    internal: bool = False
    categories: str = 'Utility;'   # freedesktop menu categories for the generated desktop entry
    mime: str = ''                 # MIME types the app can open (desktop entry MimeType=)
    keywords: str = ''

APPS = [
    App('files', 'Files', 'files', internal=True, categories='System;FileManager;', mime='inode/directory;', keywords='folders;documents;'),
    App('chatgpt', 'ChatGPT', 'chatgpt', ('chatgpt',), categories='Network;Utility;', keywords='assistant;ai;chat;'),
    App('claude', 'Claude', 'claude', ('claude-desktop',), categories='Network;Utility;', keywords='assistant;ai;chat;'),
    App('venture', 'Venture', 'browser', ('amerika-venture', 'firefox', 'chromium'), categories='Network;WebBrowser;', mime='text/html;x-scheme-handler/http;x-scheme-handler/https;', keywords='web;browser;internet;'),
    App('paper', 'Paper', 'file-document', ('euro-office-euro-office --new:word',), categories='Office;WordProcessor;', mime='application/vnd.oasis.opendocument.text;application/msword;application/vnd.openxmlformats-officedocument.wordprocessingml.document;', keywords='word;documents;writing;'),
    App('digits', 'Digits', 'file-spreadsheet', ('euro-office-euro-office --new:cell',), categories='Office;Spreadsheet;', mime='application/vnd.oasis.opendocument.spreadsheet;text/csv;application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;', keywords='spreadsheet;excel;tables;'),
    App('slides', 'Slides', 'file-presentation', ('euro-office-euro-office --new:slide',), categories='Office;Presentation;', mime='application/vnd.oasis.opendocument.presentation;application/vnd.openxmlformats-officedocument.presentationml.presentation;', keywords='presentation;powerpoint;'),
    App('makbox', 'MakBox', 'makbox', ('makos-studio-app makbox',), categories='AudioVideo;Audio;Midi;', keywords='music;compose;synth;'),
    App('render', 'Render', 'render', ('makos-studio-app render',), categories='Graphics;3DGraphics;', keywords='3d;render;modeling;'),
    App('engine', 'Engine', 'engine', ('makos-studio-app engine',), categories='Development;Game;', keywords='game;engine;'),
    App('sprite', 'Sprite', 'sprite', ('makos-studio-app sprite',), categories='Graphics;2DGraphics;RasterGraphics;', keywords='pixel;art;animation;'),
    App('studio', 'Studio', 'studio', ('makos-studio-app studio',), categories='Development;', keywords='create;games;projects;'),
    App('terminal', 'Terminal', 'terminal', ('ptyxis --new-window', 'konsole --separate', 'xterm'), categories='System;TerminalEmulator;', keywords='shell;command;console;'),
    App('text-editor', 'Text Editor', 'text-editor', internal=True, categories='Utility;TextEditor;', mime='text/plain;text/markdown;', keywords='notes;edit;code;'),
    App('calculator', 'Calculator', 'calculator', internal=True, categories='Utility;Calculator;', keywords='math;scientific;'),
    App('preview', 'Preview', 'preview', internal=True, categories='Graphics;Viewer;', mime='application/pdf;image/png;image/jpeg;image/gif;image/webp;image/bmp;image/tiff;', keywords='pdf;image;viewer;'),
    App('pictures', 'Pictures', 'photos', internal=True, categories='Graphics;Photography;Viewer;', mime='image/jpeg;image/png;image/webp;', keywords='photos;albums;slideshow;'),
    App('tunes', 'Tunes', 'music', internal=True, categories='AudioVideo;Audio;Player;', mime='audio/mpeg;audio/flac;audio/ogg;audio/x-wav;audio/mp4;audio/aac;', keywords='music;songs;player;'),
    App('movies', 'Movies', 'video', internal=True, categories='AudioVideo;Video;Player;', mime='video/mp4;video/x-matroska;video/webm;video/x-msvideo;video/quicktime;video/ogg;', keywords='video;films;player;'),
    App('notes', 'Notes', 'notes', internal=True, categories='Utility;', keywords='memo;folders;'),
    App('calendar', 'Calendar', 'calendar', internal=True, categories='Office;Calendar;', mime='text/calendar;', keywords='events;schedule;ics;'),
    App('activity', 'Activity', 'activity', internal=True, categories='System;Monitor;', keywords='processes;cpu;memory;task manager;'),
    App('disk-utility', 'Disk Utility', 'disk-utility', internal=True, categories='System;Filesystem;', keywords='disks;drives;partitions;smart;'),
    App('system-info', 'System Information', 'system-info', internal=True, categories='System;', keywords='about;hardware;'),
    App('screenshot', 'Screenshot', 'screenshot', internal=True, categories='Utility;Graphics;', keywords='capture;screen;'),
    App('software-center', 'Software Center', 'software-center', internal=True, categories='System;PackageManager;', keywords='install;apps;updates;packages;'),
    App('settings', 'Settings', 'settings', internal=True, categories='Settings;', keywords='preferences;system;'),
    App('seek', 'Seek', 'seek', internal=True, keywords='search;find;'),
    App('spread', 'Spread', 'spread', internal=True, keywords='windows;overview;'),
    App('desktops', 'Desks', 'desktops', internal=True, keywords='workspaces;virtual desktops;'),
    App('widgets', 'Widgets', 'widgets', internal=True, keywords='dashboard;clock;weather;'),
    App('trash-empty', 'Trash', 'trash-empty', internal=True, keywords='bin;deleted;'),
]
BY_ID = {a.id: a for a in APPS}


def resolve(app, which):
    import shlex
    for candidate in app.command:
        argv = shlex.split(candidate)
        if which(argv[0]):
            return argv
    return None
