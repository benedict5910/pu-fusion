"""Minimal stand-in for Streamlit/Altair so the dashboard script can be executed headless in CI
without the real packages (logic smoke test only; layout is verified on the real app).

Records markdown/html output and widget calls; buttons return values from `PRESS`.
"""
import sys
import types


class _Any:
    """Chainable no-op object (Altair charts, containers, column configs ...)."""

    def __init__(self, name="any"):
        self._name = name

    def __getattr__(self, k):
        return _Any(k)

    def __call__(self, *a, **k):
        return self

    def __add__(self, o):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


class _Box:
    def __init__(self, log):
        self.log = log

    def markdown(self, s, **k):
        self.log.append(str(s))

    def line_chart(self, *a, **k):
        self.log.append("<chart>")

    def altair_chart(self, *a, **k):
        self.log.append("<altair>")

    def empty(self):
        return _Box(self.log)

    def selectbox(self, label, options, key=None, **k):
        return st_mod.selectbox(label, options, key=key, **k)

    def __getattr__(self, k):
        return getattr(st_mod, k)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


st_mod = types.ModuleType("streamlit")
st_mod.LOG = []
st_mod.PRESS = set()
st_mod.session_state = SessionState()


def _passthrough(f=None, **k):
    return f if f else (lambda g: g)


def _widget(label, options=None, key=None, value=None, **k):
    ss = st_mod.session_state
    if key is not None:
        if key not in ss:
            ss[key] = value if value is not None else (options[0] if options else None)
        return ss[key]
    return value if value is not None else (options[0] if options else None)


def _button(label, key=None, on_click=None, args=(), **k):
    pressed = label in st_mod.PRESS or (key in st_mod.PRESS if key else False)
    if pressed:
        st_mod.PRESS.discard(label)
        if on_click:
            on_click(*args)
    return pressed


def _columns(spec, **k):
    n = spec if isinstance(spec, int) else len(spec)
    return [_Box(st_mod.LOG) for _ in range(n)]


st_mod.set_page_config = lambda **k: None
st_mod.markdown = lambda s, **k: st_mod.LOG.append(str(s))
st_mod.write = st_mod.caption = st_mod.subheader = st_mod.header = st_mod.title = st_mod.info = \
    lambda *a, **k: st_mod.LOG.append(" ".join(map(str, a)))
st_mod.divider = lambda: None
st_mod.cache_resource = st_mod.cache_data = _passthrough
st_mod.radio = st_mod.selectbox = st_mod.select_slider = st_mod.text_input = _widget
st_mod.slider = lambda label, lo, hi, value=None, key=None, **k: _widget(label, None, key, value if value is not None else lo)
st_mod.button = _button
st_mod.download_button = lambda label, data, *a, **k: st_mod.LOG.append(f"<download {label} {len(data)}B>")
st_mod.columns = _columns
st_mod.tabs = lambda names: [_Box(st_mod.LOG) for _ in names]
st_mod.container = lambda **k: _Box(st_mod.LOG)
st_mod.expander = lambda *a, **k: _Box(st_mod.LOG)
st_mod.empty = lambda: _Box(st_mod.LOG)
st_mod.sidebar = _Box(st_mod.LOG)
st_mod.line_chart = lambda *a, **k: st_mod.LOG.append("<chart>")
st_mod.altair_chart = lambda *a, **k: st_mod.LOG.append("<altair>")
st_mod.dataframe = lambda df, **k: st_mod.LOG.append(f"<table rows={len(df)}>")
st_mod.image = lambda *a, **k: st_mod.LOG.append("<image>")
st_mod.column_config = _Any("column_config")


def install():
    sys.modules["streamlit"] = st_mod
    if "altair" not in sys.modules:
        try:
            import altair  # noqa: F401
        except ImportError:
            sys.modules["altair"] = _Any("altair")
    return st_mod
