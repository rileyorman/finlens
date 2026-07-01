"""Unit tests for queue item 2 cosmetic helpers:
- _escape_md_dollars (app.py)
- _to_yfinance_ticker (modules/market_data.py)
"""
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# _to_yfinance_ticker
# ---------------------------------------------------------------------------

from modules.market_data import _to_yfinance_ticker


@pytest.mark.parametrize("ticker, expected", [
    ("REI.UN",  "REI-UN.TO"),
    ("rei.un",  "REI-UN.TO"),   # case-insensitive normalisation
    ("NFG",     "NFG.V"),       # CAD listing keeps New Found Gold ratios currency-consistent
    ("BCE.PR.A", "BCE-PR-A.TO"),
    ("AAPL",   "AAPL"),         # plain US ticker unchanged
    ("SHOP.TO", "SHOP.TO"),     # already has .TO suffix
    ("CVE.V",   "CVE.V"),       # .V suffix
    ("AC.CN",   "AC.CN"),       # .CN suffix
    ("NEO.NE",  "NEO.NE"),      # .NE suffix
    ("",        ""),            # empty string
])
def test_to_yfinance_ticker(ticker, expected):
    assert _to_yfinance_ticker(ticker) == expected


# ---------------------------------------------------------------------------
# _escape_md_dollars
# We import it directly by loading app.py's module.  Because app.py is a
# Streamlit entrypoint it has top-level side effects, so we patch st and the
# heavy imports before importing.
# ---------------------------------------------------------------------------

def _import_escape_md_dollars():
    """Import _escape_md_dollars without running the full Streamlit app."""
    # Stub out streamlit and other heavy deps so the module-level code in
    # app.py doesn't execute UI calls during import.
    for mod_name in ["streamlit", "streamlit.components", "streamlit.components.v1"]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # Provide minimal streamlit attributes that top-level app.py code touches
    st_stub = sys.modules["streamlit"]
    for attr in [
        "set_page_config", "session_state", "sidebar", "columns", "expander",
        "markdown", "write", "info", "caption", "divider", "container",
        "button", "query_params", "spinner", "metric", "error", "warning",
        "success", "stop", "rerun",
    ]:
        if not hasattr(st_stub, attr):
            setattr(st_stub, attr, lambda *a, **kw: None)

    if not hasattr(st_stub, "session_state"):
        st_stub.session_state = {}

    # Import the function by executing only up to its definition
    import ast, os
    app_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_path, encoding="utf-8") as f:
        source = f.read()

    # Extract just the function source via AST so we don't run the whole file
    tree = ast.parse(source)
    func_src = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_escape_md_dollars":
            func_src = ast.get_source_segment(source, node)
            break

    assert func_src is not None, "_escape_md_dollars not found in app.py"
    namespace = {}
    exec(func_src, namespace)  # noqa: S102
    return namespace["_escape_md_dollars"]


_escape_md_dollars = _import_escape_md_dollars()


@pytest.mark.parametrize("text, expected", [
    ("Revenue was $1.2B",       r"Revenue was \$1.2B"),
    ("$5M and $10M",            r"\$5M and \$10M"),
    ("No dollars here",         "No dollars here"),
    ("",                        ""),
    (None,                      ""),
    (r"Already escaped \$100",  r"Already escaped \\$100"),  # \ not special for us
])
def test_escape_md_dollars(text, expected):
    assert _escape_md_dollars(text) == expected
