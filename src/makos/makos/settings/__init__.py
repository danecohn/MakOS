"""MakkOS Settings package: one module per pane (pane_*.py), a registry (no GTK), and the GTK window in `app`."""


def __getattr__(name):
    # `from makos.settings import Settings` loads GTK lazily so `makos.common` can import settings.model without a display.
    if name == 'Settings':
        from .app import Settings
        return Settings
    raise AttributeError(name)
