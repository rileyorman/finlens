"""Display text helpers for the resource economics panel."""
from __future__ import annotations


NO_VALUE_LABEL = "\u2014"
CRUDE_WCS_CAVEAT = "Canadian producers may realize WCS-differential pricing."

# Price units per proxy symbol, for chart axes and spot labels.
PROXY_UNITS = {
    "CL=F": "US$/bbl",
    "GC=F": "US$/oz",
    "HG=F": "US$/lb",
    "NG=F": "US$/MMBtu",
    # ETF fallbacks trade as shares, not the underlying unit.
    "GLD": "US$/share",
    "USO": "US$/share",
    "COPX": "US$/share",
    "UNG": "US$/share",
}


def build_commodity_display_text(
    commodity: str | None,
    proxy_used: str | None,
) -> dict[str, str]:
    """Build commodity labels without leaking header-only qualifiers to cards."""
    commodity_label = (commodity or NO_VALUE_LABEL).title()
    header_label = commodity_label
    if commodity:
        header_label = f"{commodity_label} (inferred from sector description)"

    return {
        "commodity_label": commodity_label,
        "header_label": header_label,
        "spot_title": f"{commodity_label} Spot",
        "unit_label": PROXY_UNITS.get(proxy_used or "", "US$"),
        "crude_caveat": _crude_proxy_caveat(commodity, proxy_used),
    }


def _crude_proxy_caveat(commodity: str | None, proxy_used: str | None) -> str:
    if commodity != "crude oil" or not proxy_used:
        return ""
    if proxy_used == "CL=F":
        return f"Proxy is WTI futures (CL=F); {CRUDE_WCS_CAVEAT}"
    return f"Proxy is {proxy_used}; {CRUDE_WCS_CAVEAT}"
