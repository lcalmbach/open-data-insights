"""
Chart generation for Open Data Insights.

Every ECharts chart function returns a plain Python dict that is the ECharts
option object (plus the private keys _width, _height and optionally
__js_functions__). _chart_to_html() serialises it to an embeddable HTML
fragment. No third-party Python wrapper is used — just json.dumps and the
ECharts CDN loaded in base.html.

Non-ECharts functions (Leaflet maps, word cloud) return ready-made HTML strings
and are listed in NON_ECHARTS_TYPES in generate_chart().
"""
from __future__ import annotations
import base64
from decimal import Decimal
import html as html_lib
import json
import logging
import re
import uuid
from io import BytesIO

import numpy as np
import pandas as pd
from wordcloud import WordCloud

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _css_width(value) -> str:
    if value is None:
        return "100%"
    if isinstance(value, (int, float)):
        return f"{int(value)}px"
    text = str(value).strip()
    return "100%" if text.lower() == "container" else text


def _css_height(value, fallback: int = 300) -> str:
    if value is None:
        return f"{fallback}px"
    if isinstance(value, (int, float)):
        return f"{int(value)}px"
    return str(value).strip()


def _x_label_rotate(data: pd.DataFrame, x_field, settings: dict) -> int:
    angle = settings.get("x_label_angle")
    if angle is not None:
        return int(angle)
    try:
        n = int(data[x_field].nunique()) if x_field else 0
        ml = max((len(str(v)) for v in data[x_field].dropna().unique()), default=0)
    except Exception:
        n, ml = 0, 0
    if n > 12 or ml > 10:
        return -40
    if n > 8 or ml > 6:
        return -25
    return 0


def _x_labels(series, fmt: str | None = None) -> list:
    """Convert a Series/iterable to string category labels, collapsing float-like ints.

    fmt="year" extracts the 4-digit year from date-like strings (e.g. "2003-07-15" → "2003").
    """
    if fmt == "year":
        try:
            parsed = pd.to_datetime(pd.Series(list(series)), errors="coerce")
            return [str(int(y)) if not pd.isna(y) else str(v)
                    for v, y in zip(series, parsed.dt.year)]
        except Exception:
            pass  # fall through to default
    result = []
    for v in series:
        try:
            iv = int(float(v))
            if float(iv) == float(v):
                result.append(str(iv))
                continue
        except (TypeError, ValueError):
            pass
        result.append(str(v))
    return result


def _clean_vals(series) -> list:
    """Convert a Series to plain Python floats; NaN/None → None (ECharts gap)."""
    return [None if pd.isna(v) else float(v) for v in series]


def _fill_vals(series, fill: float = 0.0) -> list:
    """Like _clean_vals but replaces NaN with fill instead of None."""
    return [fill if pd.isna(v) else float(v) for v in series]


def _mark_line_opt(settings: dict) -> dict | None:
    """Build an ECharts markLine option from reference_lines settings, or None."""
    reference_lines = settings.get("reference_lines") or []
    if not isinstance(reference_lines, list):
        return None
    items = []
    for line in reference_lines:
        if not isinstance(line, dict):
            continue
        lt = str(line.get("type") or "").upper()
        label = line.get("label", "")
        ls = {"color": line.get("color", "red"), "width": line.get("width", 1)}
        if lt == "V" and "x" in line:
            items.append({"xAxis": line["x"], "name": label, "lineStyle": ls})
        elif lt == "H" and "y" in line:
            items.append({"yAxis": line["y"], "name": label, "lineStyle": ls})
    return {"silent": False, "data": items} if items else None


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _chart_to_html(option: dict, chart_id: str) -> str:
    """Serialise an ECharts option dict to an embeddable HTML+JS fragment."""
    width = option.pop("_width", "100%")
    height = option.pop("_height", "300px")
    js_functions = option.pop("__js_functions__", {})
    options_json = json.dumps(option)
    for placeholder, func_code in js_functions.items():
        options_json = options_json.replace(f'"{placeholder}"', func_code)
    return (
        f'<div id="{chart_id}" style="width:{width};height:{height};"></div>\n'
        f"<script>\n"
        f"(function(){{\n"
        f'  var dom = document.getElementById("{chart_id}");\n'
        f"  var chart = echarts.init(dom);\n"
        f"  window.__echartsInstances = window.__echartsInstances || {{}};\n"
        f'  window.__echartsInstances["{chart_id}"] = chart;\n'
        f"  chart.setOption({options_json});\n"
        f"}})();\n"
        f"</script>"
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

NON_ECHARTS_TYPES = {"wordcloud", "map_markers", "map-markers", "choropleth", "chloropleth", "simulation"}


def generate_chart(data, settings, chart_id: str) -> str:
    """Return a self-contained HTML fragment for the requested chart type."""
    try:
        chart_functions = {
            "line": create_line_chart,
            "bar": create_bar_chart,
            "bar_stacked": create_bar_stacked_chart,
            "area": create_area_chart,
            "scatter": create_point_chart,
            "pie": create_pie_chart,
            "heatmap": create_heatmap,
            "histogram": create_histogram,
            "map_markers": create_map_markers,
            "chloropleth": create_chloropleth,
            "wordcloud": create_word_cloud,
            "radar": create_radar_chart,
            "ranking_bar": create_ranking_bar_chart,
        }
        cs = settings.copy() if hasattr(settings, "copy") else dict(settings)
        cs.setdefault("chart_id", chart_id)
        ct_raw = cs.get("type")
        if hasattr(ct_raw, "value"):
            ct_raw = ct_raw.value
        ct = str(ct_raw).lower() if ct_raw is not None else ""
        result = chart_functions.get(ct, create_line_chart)(data, cs)
        if ct in NON_ECHARTS_TYPES:
            return result
        return _chart_to_html(result, chart_id)
    except Exception as e:
        logger.error("Error generating chart: %s", e)
        return f'<div id="{chart_id}" class="chart-error">Error generating chart: {e}</div>'


def generate_chloropleth(data, settings, chart_id=None) -> str:
    cs = settings.copy() if hasattr(settings, "copy") else dict(settings)
    if chart_id:
        cs.setdefault("chart_id", chart_id)
    return create_chloropleth(data, cs)


# ---------------------------------------------------------------------------
# Line chart
# ---------------------------------------------------------------------------

def _build_series_data(
    y_series,
    x_series=None,
    r_series=None,
    extra_df=None,
    extra_cols: list | None = None,
    r_min_px: int = 4,
    r_max_px: int = 30,
    r_scale: str = "linear",
    r_lo_override=None,
    r_hi_override=None,
) -> list:
    """Build ECharts per-point data items, optionally with proportional symbolSize and extra tooltip fields.

    r_scale controls how the normalized radius [0,1] maps to pixel size:
      "linear" — uniform mapping (default)
      "sqrt"   — emphasises large values moderately
      "pow2"   — squares the ratio, making outliers stand out strongly
    """
    import math

    def _apply_scale(t: float) -> float:
        if r_scale == "sqrt":
            return math.sqrt(t)
        if r_scale == "pow2":
            return t * t
        return t  # linear

    r_num = pd.to_numeric(r_series, errors="coerce") if r_series is not None else None
    if r_num is not None:
        r_lo = r_lo_override if r_lo_override is not None else r_num.min()
        r_hi = r_hi_override if r_hi_override is not None else r_num.max()
        r_span = (r_hi - r_lo) if r_hi != r_lo else 1

    items = []
    indices = range(len(y_series))
    for i, y in zip(indices, y_series):
        if pd.isna(y):
            items.append(None)
            continue
        if x_series is not None:
            x_val = x_series.iloc[i] if hasattr(x_series, "iloc") else x_series[i]
            item: dict = {"value": [str(x_val), float(y)]}
        else:
            item: dict = {"value": float(y)}
        if r_num is not None:
            r = r_num.iloc[i] if hasattr(r_num, "iloc") else r_num[i]
            if pd.isna(r):
                size = r_min_px
            else:
                t = _apply_scale((r - r_lo) / r_span)
                size = round(r_min_px + t * (r_max_px - r_min_px))
            item["symbolSize"] = size
            item["symbol"] = "circle"
        if extra_df is not None and extra_cols:
            row = extra_df.iloc[i] if hasattr(extra_df, "iloc") else extra_df[i]
            item["extra"] = {col: str(row[col]) if not pd.isna(row[col]) else "" for col in extra_cols if col in row}
        items.append(item)
    return items


def _fmt_scalar(value) -> str:
    """Render a cell for display: whole numbers lose the .0 pandas gives them."""
    scalar = _json_scalar(value)
    if isinstance(scalar, float) and scalar.is_integer():
        return str(int(scalar))
    return str(scalar)


def _series_points(df_s, x_col: str, y_col: str, tooltip_cols: list):
    """Build [x, y] points, or {value, extra} items when tooltip columns are wanted."""
    xs = [_json_scalar(v) for v in df_s[x_col].tolist()]
    ys = _clean_vals(df_s[y_col])
    if not tooltip_cols:
        return [[x, y] for x, y in zip(xs, ys)]
    points = []
    for i, (x, y) in enumerate(zip(xs, ys)):
        row = df_s.iloc[i]
        extra = {
            col: ("" if pd.isna(row[col]) else _fmt_scalar(row[col]))
            for col in tooltip_cols
            if col in row
        }
        points.append({"value": [x, y], "extra": extra})
    return points


def _json_scalar(value):
    """Convert a cell to something json.dumps accepts (Decimal -> int/float)."""
    if isinstance(value, Decimal):
        as_float = float(value)
        return int(as_float) if as_float.is_integer() else as_float
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def _sort_key(value):
    """Sort series values numerically when possible, else as text."""
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def _series_group_values(df, series_by_col: str, group_col: str | None) -> dict:
    """Map each group to the numeric range of its series values, for gradients."""
    if not group_col or group_col not in df.columns:
        return {}
    ranges: dict = {}
    for group, chunk in df.groupby(group_col):
        values = []
        for v in chunk[series_by_col].dropna().unique():
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
        if values:
            ranges[str(group)] = (min(values), max(values))
    return ranges


def _lerp_hex(lo_hex: str, hi_hex: str, t: float) -> str:
    """Linearly interpolate between two #rrggbb colours."""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    lo, hi = lo_hex.lstrip("#"), hi_hex.lstrip("#")
    parts = []
    for i in (0, 2, 4):
        a, b = int(lo[i:i + 2], 16), int(hi[i:i + 2], 16)
        parts.append(f"{round(a + (b - a) * t):02x}")
    return "#" + "".join(parts)


def _group_series_colour(style: dict, group: str, series_value, group_years: dict):
    """Resolve one series' colour, applying a within-group gradient when configured.

    A `gradient` of two colours shades members by their position in the group's
    range — older years lighter, recent years darker — so a long-term trend stays
    visible instead of collapsing into a flat block of grey.
    """
    gradient = style.get("gradient")
    if gradient and len(gradient) == 2 and group in group_years:
        lo, hi = group_years[group]
        try:
            value = float(series_value)
        except (TypeError, ValueError):
            return style.get("color")
        t = 0.5 if hi == lo else (value - lo) / (hi - lo)
        return _lerp_hex(gradient[0], gradient[1], t)
    return style.get("color")


def create_line_chart(data, settings: dict) -> dict:
    settings = settings.copy()
    x_col = settings.get("x", "")
    y_col = settings.get("y", "")
    color_col = settings.get("color")
    # Draw one line per `series_by` value, styled by `series_group`. Without this a
    # `color` column produces one line per *group*, merging all its members.
    series_by_col = settings.get("series_by")
    group_col = settings.get("series_group")
    series_group_styles = settings.get("series_group_styles") or {}
    series_years: list = []
    # Unlike other branches, keep the y column: these tooltips list named columns
    # verbatim rather than appending extras to a value line.
    series_tooltip_cols = list(settings.get("tooltips") or []) if series_by_col else []
    radius_col = settings.get("radius")
    radius_max_px = int(settings.get("radius_max", 30))
    radius_min_px = int(settings.get("radius_min", 4))
    radius_scale = settings.get("radius_scale", "linear")
    x_fmt = settings.get("x_format")
    x_type = settings.get("x_type", "category")  # "time" for date-proportional axis
    tooltip_cols = [c for c in (settings.get("tooltips") or []) if c != y_col]
    symbol_size = settings.get("symbol_size")  # explicit px size; None = ECharts default
    _use_item_trigger = False  # pivot branch keeps trigger:"axis"; others switch to "item"

    df = pd.DataFrame(data).copy()
    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))
    smooth = settings.get("interpolate") in ("monotone", "cardinal", "catmull-rom")
    show_symbol = settings.get("show_points", False)
    mark_line = _mark_line_opt(settings)

    _TEN_YEARS_MS = 10 * 365.25 * 24 * 3600 * 1000

    if x_type == "time":
        x_interval_ms = int(settings.get("x_tick_years", 10)) * _TEN_YEARS_MS / 10
        x_axis_cfg: dict = {
            "type": "time",
            "name": settings.get("x_title", ""),
            "minInterval": x_interval_ms,
            "maxInterval": x_interval_ms,
            "axisLabel": {"formatter": "{yyyy}"},
        }
    else:
        x_axis_cfg = {
            "type": "category",
            "name": settings.get("x_title", x_col),
            "axisLabel": {"rotate": _x_label_rotate(df, x_col, settings)},
        }

    option: dict = {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "axis"},
        "xAxis": x_axis_cfg,
        "yAxis": {"type": "value", "name": settings.get("y_title", y_col)},
    }

    y_domain = settings.get("y_domain")
    if y_domain and len(y_domain) == 2:
        option["yAxis"]["min"] = y_domain[0]
        option["yAxis"]["max"] = y_domain[1]

    if settings.get("focus_line"):
        fl = settings["focus_line"]
        focus_val = str(fl["color_value"])
        focus_color = fl["line_color"]
        focus_width = fl.get("line_width", 2)
        bg_color = settings.get("bg_line", {}).get("line_color", "#cccccc")
        series_col = color_col or "Year"

        pivot = df.pivot_table(index=x_col, columns=series_col, values=y_col, aggfunc="first")
        pivot = pivot.sort_index()
        option["xAxis"]["data"] = _x_labels(pivot.index, x_fmt)
        option["legend"] = {"show": False}
        option["series"] = []
        for s_val in pivot.columns:
            is_focus = str(s_val) == focus_val
            s: dict = {
                "type": "line", "name": str(s_val),
                "data": _clean_vals(pivot[s_val]),
                "smooth": smooth, "symbol": "none",
                "lineStyle": {
                    "color": focus_color if is_focus else bg_color,
                    "width": focus_width if is_focus else 1,
                    "opacity": 1.0 if is_focus else 0.5,
                },
            }
            if is_focus and mark_line:
                s["markLine"] = mark_line
            option["series"].append(s)

    elif color_col and x_type == "time":
        # Single grey connecting line + one scatter series per colour group.
        # Pivot approach breaks here because it creates disconnected per-month lines.
        df_s = df.sort_values(x_col).reset_index(drop=True)
        use_radius = bool(radius_col and radius_col in df_s.columns)
        use_extra = bool(tooltip_cols)

        # Global radius bounds so dot sizes are comparable across groups
        r_global = pd.to_numeric(df_s[radius_col], errors="coerce") if use_radius else None
        r_lo_g = float(r_global.min()) if r_global is not None else None
        r_hi_g = float(r_global.max()) if r_global is not None else None

        # Base line — connects all points in time order, no markers
        base_data = _build_series_data(df_s[y_col], x_series=df_s[x_col])
        base_s: dict = {
            "type": "line", "name": "_base",
            "data": base_data,
            "smooth": smooth,
            "symbol": "none",
            "lineStyle": {"color": settings.get("line_color", "#e0e0e0")},
            "emphasis": {"disabled": True},
            "tooltip": {"show": False},
        }
        option["series"] = [base_s]

        lo = settings.get("legend_order")
        color_vals = df_s[color_col].dropna().unique()
        if lo:
            present = set(str(v) for v in color_vals)
            color_vals = [v for v in lo if str(v) in present] + [
                v for v in color_vals if str(v) not in {str(x) for x in lo}
            ]
        option["legend"] = {"data": [str(v) for v in color_vals]}

        for cv in color_vals:
            df_cv = df_s[df_s[color_col] == cv].reset_index(drop=True)
            scatter_data = _build_series_data(
                df_cv[y_col],
                x_series=df_cv[x_col],
                r_series=df_cv[radius_col] if use_radius else None,
                extra_df=df_cv if use_extra else None,
                extra_cols=tooltip_cols if use_extra else None,
                r_min_px=radius_min_px,
                r_max_px=radius_max_px,
                r_scale=radius_scale,
                r_lo_override=r_lo_g,
                r_hi_override=r_hi_g,
            )
            scatter_s: dict = {
                "type": "scatter", "name": str(cv),
                "data": scatter_data,
                "label": {"show": False},
            }
            option["series"].append(scatter_s)
        _use_item_trigger = True

    elif series_by_col:
        # One line per `series_by` value (e.g. per year), styled by the group it
        # belongs to (e.g. year_group). Pivoting on the group instead would collapse
        # every year sharing a group into a single line.
        option["series"] = []
        groups_seen: list[str] = []
        group_years = _series_group_values(df, series_by_col, group_col)

        for s_val in sorted(df[series_by_col].dropna().unique(), key=_sort_key):
            df_s = df[df[series_by_col] == s_val].sort_values(x_col)
            group = str(df_s[group_col].iloc[0]) if group_col else ""
            style = dict(series_group_styles.get(group, {}))

            colour = _group_series_colour(style, group, s_val, group_years)
            line_style = {"width": style.get("width", 1)}
            if colour:
                line_style["color"] = colour
            if style.get("opacity") is not None:
                line_style["opacity"] = style["opacity"]

            # The legend takes its swatch colour from itemStyle, not lineStyle, so
            # without this it would fall back to the default palette and show
            # colours the lines do not use. For a gradient group the first series is
            # the palest member, so prefer an explicit colour to represent the group.
            legend_colour = style.get("legend_color") or style.get("color") or colour

            series: dict = {
                "type": "line",
                # Series in a group share a name so the legend shows one entry per
                # group rather than one per year; ECharts dedupes legend by name.
                "name": group or str(s_val),
                "itemStyle": {"color": legend_colour} if legend_colour else {},
                # Coerce x: psycopg returns numeric columns as Decimal, which
                # json.dumps cannot serialise.
                "data": _series_points(df_s, x_col, y_col, series_tooltip_cols),
                "smooth": smooth,
                # Deliberately NOT symbol:"none": that removes the symbol entirely,
                # including its hit area, so an item tooltip can never fire.
                # showSymbol:false hides symbols but ECharts still draws one under
                # the cursor on hover, which is what the tooltip attaches to.
                "symbol": "circle",
                "symbolSize": 8,
                "showSymbol": False,
                "lineStyle": line_style,
                "z": style.get("z", 2),
                "emphasis": {"focus": "series", "lineStyle": {"width": style.get("width", 1) + 1}},
            }
            if group and group not in groups_seen:
                groups_seen.append(group)
            option["series"].append(series)
            series_years.append(s_val)

        # x is numeric and shared across every year (e.g. day_in_year 1..366).
        option["xAxis"] = {
            "type": "value",
            "name": settings.get("x_title", x_col),
            "min": settings.get("x_min"),
            "max": settings.get("x_max"),
        }
        option["xAxis"] = {k: v for k, v in option["xAxis"].items() if v is not None}

        legend_order = settings.get("legend_order") or []
        ordered = [g for g in legend_order if g in groups_seen]
        ordered += [g for g in groups_seen if g not in ordered]
        # ECharts draws a line *with the series symbol* for line legends and does not
        # inherit symbol:"none", so the default swatch shows a marker this chart never
        # plots. A thin roundRect reads as a plain line segment instead.
        option["legend"] = {
            "data": ordered,
            "icon": settings.get("legend_icon", "roundRect"),
            "itemWidth": settings.get("legend_item_width", 26),
            "itemHeight": settings.get("legend_item_height", 3),
        }

    elif color_col:
        pivot = df.pivot_table(index=x_col, columns=color_col, values=y_col, aggfunc="first")
        pivot = pivot.sort_index()
        lo = settings.get("legend_order")
        series_order = list(lo) if lo else list(pivot.columns)
        option["xAxis"]["data"] = _x_labels(pivot.index, x_fmt)
        option["legend"] = {"data": [str(s) for s in series_order]}
        r_pivot = None
        if radius_col and radius_col in df.columns:
            r_pivot = df.pivot_table(index=x_col, columns=color_col, values=radius_col, aggfunc="first")
            r_pivot = r_pivot.sort_index()
        option["series"] = []
        for s_val in series_order:
            if s_val not in pivot.columns:
                continue
            use_radius = r_pivot is not None and s_val in r_pivot.columns
            if use_radius or tooltip_cols:
                series_data = _build_series_data(
                    pivot[s_val],
                    r_series=r_pivot[s_val] if use_radius else None,
                    r_min_px=radius_min_px,
                    r_max_px=radius_max_px,
                    r_scale=radius_scale,
                )
                sym = "circle" if use_radius else ("circle" if show_symbol else "none")
            else:
                series_data = _clean_vals(pivot[s_val])
                sym = "circle" if show_symbol else "none"
            s = {
                "type": "line", "name": str(s_val),
                "data": series_data,
                "smooth": smooth,
                "symbol": sym,
                "label": {"show": False},
            }
            if mark_line:
                s["markLine"] = mark_line
            option["series"].append(s)

    else:
        df_s = df.sort_values(x_col).reset_index(drop=True)
        option["legend"] = {"show": False}
        use_radius = radius_col and radius_col in df_s.columns
        use_extra = bool(tooltip_cols)
        if x_type == "time":
            # Time axis: pass x values as part of each data item; no xAxis.data needed
            series_data = _build_series_data(
                df_s[y_col],
                x_series=df_s[x_col],
                r_series=df_s[radius_col] if use_radius else None,
                extra_df=df_s if use_extra else None,
                extra_cols=tooltip_cols if use_extra else None,
                r_min_px=radius_min_px,
                r_max_px=radius_max_px,
                r_scale=radius_scale,
            )
            sym = "circle" if use_radius else ("circle" if show_symbol else "none")
        elif use_radius or use_extra:
            option["xAxis"]["data"] = _x_labels(df_s[x_col], x_fmt)
            series_data = _build_series_data(
                df_s[y_col],
                r_series=df_s[radius_col] if use_radius else None,
                extra_df=df_s if use_extra else None,
                extra_cols=tooltip_cols if use_extra else None,
                r_min_px=radius_min_px,
                r_max_px=radius_max_px,
                r_scale=radius_scale,
            )
            sym = "circle" if use_radius else ("circle" if show_symbol else "none")
        else:
            option["xAxis"]["data"] = _x_labels(df_s[x_col], x_fmt)
            series_data = _clean_vals(df_s[y_col])
            sym = "circle" if show_symbol else "none"
        s = {
            "type": "line", "name": y_col,
            "data": series_data,
            "smooth": smooth,
            "symbol": sym,
            "label": {"show": False},
        }
        if settings.get("line_color") or settings.get("marker_color"):
            s["lineStyle"] = {"color": settings.get("line_color", "inherit")}
            s["itemStyle"] = {"color": settings.get("marker_color") or settings.get("line_color")}
        if mark_line:
            s["markLine"] = mark_line
        option["series"] = [s]
        _use_item_trigger = True

    if symbol_size is not None:
        for s in option.get("series", []):
            if s.get("type") == "line":
                s["symbolSize"] = int(symbol_size)

    if series_by_col and option.get("series"):
        # An axis tooltip would list every series at that x — 163 lines for a
        # per-year chart. Trigger on the hovered line instead, and look the series
        # value up by index because series share a name for legend grouping.
        years_json = json.dumps([_fmt_scalar(v) for v in series_years])
        if series_tooltip_cols:
            # Render exactly the columns named in `tooltips`, carried per point.
            tooltip_fn = (
                "function(p){"
                f"var names={years_json};"
                "var label=names[p.seriesIndex]!==undefined?names[p.seriesIndex]:p.seriesName;"
                "var html='<b>'+label+'</b>';"
                "var e=(p.data&&p.data.extra)||{};"
                "for(var k in e){if(e.hasOwnProperty(k))html+='<br/>'+k+': '+e[k];}"
                "return html;}"
            )
        else:
            tooltip_fn = (
                "function(p){"
                f"var names={years_json};"
                "var v=Array.isArray(p.value)?p.value:[p.name,p.value];"
                "var label=names[p.seriesIndex]!==undefined?names[p.seriesIndex]:p.seriesName;"
                "return '<b>'+label+'</b><br/>'"
                f"+{json.dumps(str(settings.get('x_title', x_col)))}+': '+v[0]"
                f"+'<br/>'+{json.dumps(str(settings.get('y_title', y_col)))}+': '+v[1];}}"
            )
        option["tooltip"] = {
            "trigger": "item",
            "formatter": "__series_tt__",
            # Without this the pointer must land exactly on the path.
            "triggerOn": "mousemove",
        }
        option.setdefault("__js_functions__", {})["__series_tt__"] = tooltip_fn

    if tooltip_cols and _use_item_trigger:
        tooltip_fn = (
            "function(params){"
            "var p=Array.isArray(params)?params[0]:params;"
            "var yVal=Array.isArray(p.value)?p.value[1]:p.value;"
            "var html='<b>'+p.name+'</b><br/>'+p.seriesName+': '+yVal;"
            "if(p.data&&p.data.extra){"
            "var e=p.data.extra;"
            "for(var k in e){if(e.hasOwnProperty(k))html+='<br/>'+k+': '+e[k];}}"
            "return html;}"
        )
        option["tooltip"] = {"trigger": "item", "formatter": "__line_tt__"}
        option["__js_functions__"] = {"__line_tt__": tooltip_fn}

    if settings.get("legend_order") and settings.get("color_range"):
        option["color"] = list(settings["color_range"])
    return option


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------

def create_bar_chart(data, settings: dict) -> dict:
    x_field = settings.get("x")
    y_field = settings.get("y")
    color_field = settings.get("color")
    is_horizontal = settings.get("horizontal", False)

    df = pd.DataFrame(data).copy()
    if y_field:
        df[y_field] = pd.to_numeric(df[y_field], errors="coerce")

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))
    rotate = _x_label_rotate(df, x_field if not is_horizontal else y_field, settings)

    x_order = settings.get("x_order")
    tooltip_cols: list = []

    if color_field:
        pivot = df.pivot_table(index=x_field, columns=color_field, values=y_field, aggfunc="sum")
        pivot.index = [str(v) for v in pivot.index]
        if x_order:
            order_strs = [str(v) for v in x_order]
            present = set(pivot.index)
            ordered = [v for v in order_strs if v in present]
            remaining = [v for v in sorted(present, key=str) if v not in set(ordered)]
            pivot = pivot.reindex(ordered + remaining, fill_value=0)
        else:
            pivot = pivot.sort_index()
        x_vals = list(pivot.index)
        lo = settings.get("legend_order")
        series_order = list(lo) if lo else list(pivot.columns)
        series = [
            {"type": "bar", "name": str(s), "data": _clean_vals(pivot[s]), "label": {"show": False}}
            for s in series_order if s in pivot.columns
        ]
    else:
        if x_field and x_order:
            order_map = {str(v): i for i, v in enumerate(x_order)}
            df_s = df.copy()
            df_s["__x_sort__"] = df_s[x_field].astype(str).map(order_map)
            df_s = df_s.sort_values("__x_sort__").drop(columns="__x_sort__")
        else:
            df_s = df.sort_values(x_field) if x_field else df
        tooltip_cols = [c for c in (settings.get("tooltips") or []) if c != y_field]
        x_vals = _x_labels(df_s[x_field]) if x_field else []
        if tooltip_cols and y_field:
            bar_data = []
            for _, row in df_s.iterrows():
                v = row[y_field]
                item: dict = {"value": None if pd.isna(v) else float(v)}
                item["extra"] = {
                    col: str(row[col]) if not pd.isna(row[col]) else ""
                    for col in tooltip_cols if col in row
                }
                bar_data.append(item)
        else:
            bar_data = _clean_vals(df_s[y_field]) if y_field else []
            tooltip_cols = []
        series = [{"type": "bar", "data": bar_data, "label": {"show": False}}]

    if is_horizontal:
        option = {
            "_width": w, "_height": h,
            "title": {"text": settings.get("title", "")},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"show": bool(color_field)},
            "xAxis": {"type": "value", "name": settings.get("x_title", y_field)},
            "yAxis": {"type": "category", "data": x_vals, "name": settings.get("y_title", x_field)},
            "series": series,
        }
    else:
        option = {
            "_width": w, "_height": h,
            "title": {"text": settings.get("title", "")},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"show": bool(color_field)},
            "xAxis": {
                "type": "category", "data": x_vals,
                "name": settings.get("x_title", x_field),
                "axisLabel": {"rotate": rotate},
            },
            "yAxis": {"type": "value", "name": settings.get("y_title", y_field)},
            "series": series,
        }

    y_domain = settings.get("y_domain")
    if y_domain and len(y_domain) == 2:
        option["yAxis"]["min"] = y_domain[0]
        option["yAxis"]["max"] = y_domain[1]
    if settings.get("color_range"):
        option["color"] = list(settings["color_range"])

    if tooltip_cols:
        tooltip_fn = (
            "function(params){"
            "var p=Array.isArray(params)?params[0]:params;"
            "var html='<b>'+p.name+'</b><br/>'+p.seriesName+': '+p.value;"
            "if(p.data&&p.data.extra){"
            "var e=p.data.extra;"
            "for(var k in e){if(e.hasOwnProperty(k))html+='<br/>'+k+': '+e[k];}}"
            "return html;}"
        )
        option["tooltip"] = {"trigger": "item", "formatter": "__bar_tt__"}
        option["__js_functions__"] = {"__bar_tt__": tooltip_fn}

    return option


# ---------------------------------------------------------------------------
# Stacked bar chart
# ---------------------------------------------------------------------------

def create_bar_stacked_chart(data, settings: dict) -> dict:
    x_field = settings.get("x")
    y_field = settings.get("y")
    color_field = settings.get("color")

    if not x_field or not y_field or not color_field:
        logger.error("Stacked bar chart requires 'x', 'y', and 'color' fields")
        return {"_width": "100%", "_height": "300px", "series": []}

    df = pd.DataFrame(data).copy()
    df[y_field] = pd.to_numeric(df[y_field], errors="coerce")

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))

    pivot = df.pivot_table(index=x_field, columns=color_field, values=y_field, aggfunc="sum")
    pivot = pivot.sort_index()
    x_vals = _x_labels(pivot.index)

    lo = settings.get("legend_order")
    series_order = list(lo) if lo else list(pivot.columns)

    if settings.get("percentage"):
        totals = pivot.sum(axis=1)
        pivot = pivot.div(totals, axis=0) * 100

    series = []
    for s_val in series_order:
        if s_val not in pivot.columns:
            continue
        series.append({
            "type": "bar", "name": str(s_val),
            "data": _fill_vals(pivot[s_val]),
            "stack": "total",
            "label": {"show": False},
            "emphasis": {"focus": "series"},
        })

    y_fmt = "{value}%" if settings.get("percentage") else "{value}"
    rotate = _x_label_rotate(df, x_field, settings)

    option = {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {
            "data": [str(s) for s in series_order],
            "orient": settings.get("legend_orient", "horizontal"),
            "top": "5%",
        },
        "grid": {"top": "20%"},
        "xAxis": {
            "type": "category", "data": x_vals,
            "name": settings.get("x_title", x_field),
            "axisLabel": {"rotate": rotate},
        },
        "yAxis": {
            "type": "value",
            "name": settings.get("y_title", y_field),
            "axisLabel": {"formatter": y_fmt},
        },
        "series": series,
    }

    if settings.get("color_range"):
        option["color"] = list(settings["color_range"])
    return option


# ---------------------------------------------------------------------------
# Area chart
# ---------------------------------------------------------------------------

def create_area_chart(data, settings: dict) -> dict:
    x_col = settings.get("x", "")
    y_col = settings.get("y", "")
    color_col = settings.get("color")
    opacity = settings.get("opacity", 0.6)
    stacked = settings.get("stacked", True)

    df = pd.DataFrame(data).copy()
    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))
    stack_val = "total" if stacked else None

    if color_col:
        pivot = df.pivot_table(index=x_col, columns=color_col, values=y_col, aggfunc="first")
        pivot = pivot.sort_index()
        x_vals = _x_labels(pivot.index)
        series = []
        for col in pivot.columns:
            s: dict = {
                "type": "line", "name": str(col),
                "data": _clean_vals(pivot[col]),
                "areaStyle": {"opacity": opacity},
                "symbol": "none", "label": {"show": False},
            }
            if stack_val:
                s["stack"] = stack_val
            series.append(s)
    else:
        df_s = df.sort_values(x_col)
        x_vals = _x_labels(df_s[x_col])
        s = {
            "type": "line", "data": _clean_vals(df_s[y_col]),
            "areaStyle": {"opacity": opacity},
            "symbol": "none", "label": {"show": False},
        }
        if stack_val:
            s["stack"] = stack_val
        series = [s]

    y_fmt = "{value}%" if settings.get("percentage") else "{value}"
    option = {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "axis"},
        "legend": {"show": bool(color_col)},
        "xAxis": {"type": "category", "data": x_vals, "name": settings.get("x_title", x_col)},
        "yAxis": {"type": "value", "name": settings.get("y_title", y_col), "axisLabel": {"formatter": y_fmt}},
        "series": series,
    }
    y_domain = settings.get("y_domain")
    if y_domain and len(y_domain) == 2:
        option["yAxis"]["min"] = y_domain[0]
        option["yAxis"]["max"] = y_domain[1]
    return option


# ---------------------------------------------------------------------------
# Scatter / point chart
# ---------------------------------------------------------------------------

def create_point_chart(data, settings: dict) -> dict:
    x_col = settings.get("x", "")
    y_col = settings.get("y", "")
    color_col = settings.get("color")
    size_col = settings.get("size")
    point_size = settings.get("point_size", 10)

    df = pd.DataFrame(data).copy()
    df[x_col] = pd.to_numeric(df[x_col], errors="coerce")
    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))

    def _rows(sub):
        sub = sub.dropna(subset=[x_col, y_col])
        if size_col and size_col in sub.columns:
            sub[size_col] = pd.to_numeric(sub[size_col], errors="coerce")
            return [[float(r[x_col]), float(r[y_col]), float(r[size_col])] for _, r in sub.iterrows()]
        return [[float(r[x_col]), float(r[y_col])] for _, r in sub.iterrows()]

    if color_col:
        series = [
            {"type": "scatter", "name": str(s_val), "data": _rows(group),
             "symbolSize": point_size, "label": {"show": False}}
            for s_val, group in df.groupby(color_col)
        ]
    else:
        series = [{"type": "scatter", "data": _rows(df), "symbolSize": point_size, "label": {"show": False}}]

    return {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "item"},
        "legend": {"show": bool(color_col)},
        "xAxis": {"type": "value", "name": settings.get("x_title", x_col), "scale": True},
        "yAxis": {"type": "value", "name": settings.get("y_title", y_col), "scale": True},
        "series": series,
    }


# ---------------------------------------------------------------------------
# Pie chart
# ---------------------------------------------------------------------------

def create_pie_chart(data, settings: dict) -> dict:
    theta_field = settings.get("theta", settings.get("y"))
    color_field = settings.get("color", settings.get("x"))

    if not theta_field or not color_field:
        logger.error("Pie chart requires 'theta'/'y' and 'color'/'x' fields")
        return {"_width": "300px", "_height": "300px", "series": []}

    df = pd.DataFrame(data).copy()
    df[theta_field] = pd.to_numeric(df[theta_field], errors="coerce")

    w = _css_width(settings.get("width", 300))
    h = _css_height(settings.get("height", 300))

    inner_r = settings.get("inner_radius", 0)
    outer_r = settings.get("outer_radius", 75)
    inner_pct = f"{inner_r}%" if isinstance(inner_r, (int, float)) else str(inner_r)
    outer_pct = f"{outer_r}%" if isinstance(outer_r, (int, float)) else str(outer_r)

    pie_data = [
        {"name": str(row[color_field]), "value": float(row[theta_field])}
        for _, row in df.dropna(subset=[theta_field]).iterrows()
    ]

    return {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "item", "formatter": "{b}: {d}%"},
        "legend": {"orient": "vertical", "left": "left"},
        "series": [{
            "type": "pie",
            "radius": [inner_pct, outer_pct],
            "data": pie_data,
            "label": {"formatter": "{b}: {d}%"},
            "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.5)"}},
        }],
    }


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

def create_heatmap(data, settings: dict) -> dict:
    x_field = settings.get("x")
    y_field = settings.get("y")
    color_field = settings.get("color")

    if not x_field or not y_field or not color_field:
        logger.error("Heatmap requires 'x', 'y', and 'color' fields")
        return {"_width": "100%", "_height": "300px", "series": []}

    df = pd.DataFrame(data).copy()
    df[color_field] = pd.to_numeric(df[color_field], errors="coerce")

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))

    def _norm(v):
        try:
            iv = int(float(v))
            if float(iv) == float(v):
                return str(iv)
        except (TypeError, ValueError):
            pass
        return str(v)

    def _sorted_cats(values, explicit_order=None):
        normed = [_norm(v) for v in values]
        if explicit_order:
            present = set(normed)
            ordered = [str(v) for v in explicit_order if str(v) in present]
            remaining = [v for v in normed if v not in set(ordered)]
            return ordered + sorted(set(remaining), key=str)
        try:
            return [str(i) for i in sorted({int(v) for v in normed})]
        except (ValueError, TypeError):
            pass
        return sorted(set(normed), key=str)

    x_vals = _sorted_cats(df[x_field].dropna().unique(), settings.get("x_order"))
    y_vals = _sorted_cats(df[y_field].dropna().unique(), settings.get("y_order"))
    x_idx = {v: i for i, v in enumerate(x_vals)}
    y_idx = {v: i for i, v in enumerate(y_vals)}

    value_rows = []
    for _, row in df.iterrows():
        xv, yv = _norm(row[x_field]), _norm(row[y_field])
        cv = row[color_field]
        xi, yi = x_idx.get(xv), y_idx.get(yv)
        if xi is not None and yi is not None and not pd.isna(cv):
            value_rows.append([xv, yv, float(cv)])

    z_min = float(df[color_field].min())
    z_max = float(df[color_field].max())
    if cd := settings.get("color_domain"):
        z_min, z_max = float(cd[0]), float(cd[-1])

    x_title = settings.get("x_title", x_field)
    y_title = settings.get("y_title", y_field)
    z_title = settings.get("color_title", color_field)
    title = settings.get("title", "")

    tooltip_fn = (
        f"function(p){{var v=p.value;"
        f"return '{x_title}: '+v[0]+'<br/>'+'{y_title}: '+v[1]+'<br/>'+'{z_title}: '+v[2];}}"
    )

    return {
        "_width": w, "_height": h,
        "__js_functions__": {"__hm_fmt__": tooltip_fn},
        "title": [{"text": title}] if title else [],
        "tooltip": {"position": "top", "formatter": "__hm_fmt__"},
        "grid": {"top": "10%", "bottom": "20%", "left": "10%", "right": "5%"},
        "xAxis": {"type": "category", "data": x_vals, "name": x_title, "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": y_vals, "name": y_title, "splitArea": {"show": True}},
        "visualMap": {"min": z_min, "max": z_max, "calculable": True,
                      "orient": "horizontal", "left": "center", "bottom": "2%"},
        "series": [{"type": "heatmap", "data": value_rows,
                    "label": {"show": settings.get("show_labels", False)},
                    "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.5)"}}}],
    }


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

def create_histogram(data, settings: dict) -> dict:
    x_field = settings.get("x")
    if not x_field:
        logger.error("Histogram requires an 'x' field.")
        return {"_width": "100%", "_height": "300px", "series": []}

    df = pd.DataFrame(data).copy()
    x_values = pd.to_numeric(df[x_field], errors="coerce").dropna().to_numpy()
    if x_values.size == 0:
        return {"_width": "100%", "_height": "300px", "series": []}

    edges = counts = None

    def _norm_edges(ea):
        ea = np.asarray(ea, dtype=float)
        if ea.ndim != 1 or ea.size < 2 or not np.all(np.diff(ea) > 0):
            raise ValueError("bin_edges must be strictly increasing with ≥2 values")
        return ea

    if settings.get("bin_edges") is not None:
        try:
            edges = _norm_edges(settings["bin_edges"])
            counts, edges = np.histogram(x_values, bins=edges)
        except Exception as exc:
            logger.warning("Invalid bin_edges: %s", exc)
            edges = None

    if edges is None:
        bin_min = settings.get("bin_min")
        bin_max = settings.get("bin_max")
        hist_range = None
        if bin_min is not None or bin_max is not None:
            lo = float(bin_min) if bin_min is not None else float(np.min(x_values))
            hi = float(bin_max) if bin_max is not None else float(np.max(x_values))
            hist_range = (lo, max(lo + 1, hi))

        bin_step = settings.get("bin_step")
        if bin_step:
            try:
                step = float(bin_step)
                start = hist_range[0] if hist_range else float(np.min(x_values))
                stop = hist_range[1] if hist_range else float(np.max(x_values))
                edges = np.arange(start, stop + step, step)
                if edges.size < 2:
                    edges = np.array([start, stop + step])
                counts, edges = np.histogram(x_values, bins=edges)
            except Exception as exc:
                logger.warning("Invalid bin_step: %s", exc)
                edges = None

    if edges is None:
        bins = int(settings.get("bins") or settings.get("max_bins") or settings.get("bin_count") or 40)
        if hist_range:
            counts, edges = np.histogram(x_values, bins=bins, range=hist_range)
        else:
            counts, edges = np.histogram(x_values, bins=bins)

    x_labels = [f"{edges[i]:.4g}" for i in range(len(edges) - 1)]
    mark_line = _mark_line_opt(settings)
    fill_color = settings.get("fill_color", "#5470c6")
    opacity = settings.get("opacity", 0.6)

    s = {
        "type": "bar",
        "data": counts.tolist(),
        "barCategoryGap": "0%",
        "itemStyle": {"color": fill_color, "opacity": opacity},
        "label": {"show": False},
    }
    if mark_line:
        s["markLine"] = mark_line

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 300))
    return {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": x_labels, "name": settings.get("x_title", x_field)},
        "yAxis": {"type": "value", "name": settings.get("y_title", "Count"), "min": 0},
        "series": [s],
    }


# ---------------------------------------------------------------------------
# Radar chart
# ---------------------------------------------------------------------------

def create_radar_chart(data, settings: dict) -> dict:
    df = pd.DataFrame(data).copy()

    cat_field = settings.get("category") or settings.get("x")
    val_field = settings.get("value") or settings.get("y")
    ser_field = settings.get("series") or settings.get("color")

    if not cat_field or cat_field not in df.columns:
        cat_field = df.columns[0] if len(df.columns) > 0 else None
    if not val_field or val_field not in df.columns:
        rem = [c for c in df.columns if c != cat_field]
        val_field = rem[0] if rem else None

    if not cat_field or not val_field:
        logger.error("Radar chart requires category and value fields")
        return {"_width": "420px", "_height": "420px", "series": []}

    df[val_field] = pd.to_numeric(df[val_field], errors="coerce").fillna(0)
    categories = list(df[cat_field].unique())
    if len(categories) < 3:
        logger.error("Radar chart requires at least 3 categories")
        return {"_width": "420px", "_height": "420px", "series": []}

    min_val = float(settings.get("min_value", 0))
    max_val = float(settings.get("max_value") or df[val_field].max())
    invert = bool(settings.get("invert", False))
    fill_alpha = float(settings.get("fill_alpha", 0.15))
    line_width = float(settings.get("line_width", 2))

    h_val = int(settings.get("height", 420))
    w_raw = settings.get("width")
    w_css = "100%" if (w_raw is None or str(w_raw).lower() == "container") else _css_width(w_raw)

    has_series = bool(ser_field and ser_field in df.columns)
    radar_data = []
    for s_val in (df[ser_field].unique() if has_series else [None]):
        subset = df[df[ser_field] == s_val] if has_series else df
        cat_map = {str(r[cat_field]): float(r[val_field]) for _, r in subset.iterrows()}
        vals = []
        for cat in categories:
            raw = cat_map.get(str(cat), min_val)
            if invert:
                v = max(min_val, min(max_val, max_val - (raw - min_val)))
            else:
                v = raw
            vals.append(v)
        radar_data.append({
            "value": vals,
            "name": str(s_val) if has_series else (settings.get("title") or ""),
        })

    return {
        "_width": w_css, "_height": f"{h_val}px",
        "title": {"text": settings.get("title", "")},
        "legend": {"show": has_series},
        "tooltip": {},
        "radar": {
            "indicator": [{"name": str(c), "max": max_val, "min": min_val} for c in categories],
            "shape": "polygon",
            "center": ["50%", "55%"],
            "radius": "58%",
            "axisName": {
                "overflow": "break",
                "width": 80,
            },
            "splitLine": {"lineStyle": {"color": "#cccccc", "width": 0.6}},
        },
        "series": [{
            "type": "radar",
            "data": radar_data,
            "areaStyle": {"opacity": fill_alpha},
            "lineStyle": {"width": line_width},
            "symbol": "circle", "symbolSize": 5,
        }],
    }


# ---------------------------------------------------------------------------
# Ranking bar chart
# ---------------------------------------------------------------------------

def create_ranking_bar_chart(data, settings: dict) -> dict:
    df = pd.DataFrame(data).copy()
    cat_field = settings.get("category") or (df.columns[0] if len(df.columns) > 0 else "category")
    val_field = settings.get("value") or (df.columns[1] if len(df.columns) > 1 else "value")
    highlight = str(settings.get("highlight", ""))
    hi_color = settings.get("highlight_color", "#e45756")
    bar_color = settings.get("bar_color", "#bbbbbb")

    df[val_field] = pd.to_numeric(df[val_field], errors="coerce")
    ascending = settings.get("sort", "descending") == "ascending"
    df = df.sort_values(val_field, ascending=ascending).reset_index(drop=True)

    w = _css_width(settings.get("width", "container"))
    h = _css_height(settings.get("height", 400))

    series_data = [
        {
            "value": float(row[val_field]) if not pd.isna(row[val_field]) else 0.0,
            "itemStyle": {"color": hi_color if str(row[cat_field]) == highlight else bar_color},
        }
        for _, row in df.iterrows()
    ]

    return {
        "_width": w, "_height": h,
        "title": {"text": settings.get("title", "")},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"show": False},
        "xAxis": {"type": "value", "name": settings.get("x_title", val_field)},
        "yAxis": {
            "type": "category",
            "data": df[cat_field].astype(str).tolist(),
            "name": settings.get("y_title", cat_field),
        },
        "series": [{"type": "bar", "data": series_data, "label": {"show": False}}],
    }


# ---------------------------------------------------------------------------
# Word cloud  (returns HTML string, not an ECharts dict)
# ---------------------------------------------------------------------------

def create_word_cloud(data, settings: dict) -> str:
    if WordCloud is None:
        return '<div class="chart-error">wordcloud library is not installed</div>'

    df = pd.DataFrame(data).copy()
    text_field = settings.get("text") or settings.get("word") or settings.get("x")
    weight_field = settings.get("weight") or settings.get("count") or settings.get("y")

    if not text_field and len(df.columns) > 0:
        text_field = df.columns[0]
    if not text_field or text_field not in df.columns:
        return '<div class="chart-error">Word cloud requires a text column</div>'

    if not weight_field or weight_field not in df.columns:
        rem = [c for c in df.columns if c != text_field]
        weight_field = rem[0] if rem else "_w"
        if weight_field == "_w":
            df["_w"] = 1

    df = df[[text_field, weight_field]].dropna(subset=[text_field])
    df[weight_field] = pd.to_numeric(df[weight_field], errors="coerce").fillna(1)
    df[text_field] = df[text_field].astype(str)

    max_words = settings.get("max_words")
    if max_words:
        try:
            df = df.sort_values(weight_field, ascending=False).head(int(max_words))
        except Exception:
            pass

    frequencies: dict = {}
    for word, weight in zip(df[text_field], df[weight_field]):
        try:
            w = float(weight)
        except (TypeError, ValueError):
            w = 1.0
        if word and w > 0:
            frequencies[word] = frequencies.get(word, 0) + w

    if not frequencies:
        return '<div class="chart-error">No data available for word cloud</div>'

    wc = WordCloud(
        width=int(settings.get("width", 700)),
        height=int(settings.get("height", 500)),
        background_color=settings.get("background_color", "white"),
        colormap=settings.get("color_scheme", "viridis"),
        max_words=max_words,
        prefer_horizontal=settings.get("prefer_horizontal", 0.9),
        stopwords=set(settings.get("stopwords", [])) if settings.get("stopwords") else None,
    ).generate_from_frequencies(frequencies)

    buf = BytesIO()
    wc.to_image().save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    chart_id = settings.get("chart_id", "word-cloud")
    title = settings.get("title", "Word Cloud")
    img_style = settings.get("img_style", "width:100%;height:auto;display:block;")
    return (
        f'<div id="{chart_id}" class="word-cloud-chart" aria-label="{title}">'
        f'<img src="data:image/png;base64,{img_b64}" alt="{title}" style="{img_style}"/></div>'
    )


# ---------------------------------------------------------------------------
# Leaflet map utilities (return HTML strings, not ECharts dicts)
# ---------------------------------------------------------------------------

def _sanitize_map_identifier(identifier):
    if not identifier:
        return None
    s = re.sub(r"[^0-9a-zA-Z_]", "_", str(identifier))
    if not s:
        return None
    return ("_" + s) if not (s[0].isalpha() or s[0] == "_") else s


def _sanitize_js_identifier(identifier):
    return _sanitize_map_identifier(identifier) or "_map"


def _css_dimension(value, *, fallback_px=400, default_unit="px"):
    if value is None:
        return f"{fallback_px}{default_unit}"
    if isinstance(value, (int, float)):
        return f"{int(value)}{default_unit}"
    text = str(value).strip()
    return f"{fallback_px}{default_unit}" if text.lower() in {"container", "100%"} else text


def _escape_js(value):
    return "null" if value is None else json.dumps(value)


def _parse_color_bins(spec):
    """Validate a `color_bins` spec into (thresholds, colors, labels).

    Keeps the palette in the graphic settings instead of hand-written hex codes in
    every SQL query. `thresholds` must be ascending, and `colors` must hold exactly
    one more entry than `thresholds` (values below the first threshold, each interval,
    and values at or above the last). Returns None when no usable spec is given.
    """
    if not isinstance(spec, dict):
        return None
    thresholds = spec.get("thresholds") or spec.get("bins")
    colors = spec.get("colors") or spec.get("palette")
    if not thresholds or not colors:
        return None
    try:
        thresholds = [float(t) for t in thresholds]
    except (TypeError, ValueError):
        return None
    if sorted(thresholds) != thresholds:
        raise ValueError("color_bins.thresholds must be in ascending order")
    if len(colors) != len(thresholds) + 1:
        raise ValueError(
            f"color_bins needs {len(thresholds) + 1} colors for "
            f"{len(thresholds)} thresholds, got {len(colors)}"
        )
    labels = spec.get("labels")
    if labels and len(labels) != len(colors):
        raise ValueError("color_bins.labels must have one entry per color")
    return thresholds, [str(c) for c in colors], list(labels) if labels else None


def _color_for_value(value, thresholds, colors):
    """Map a numeric value onto its bin colour, or None when it is not numeric.

    Bins are half-open [lower, upper): a value equal to a threshold falls into the
    bin starting at it, so boundary values land in exactly one bin.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:  # NaN
        return None
    for index, threshold in enumerate(thresholds):
        if numeric < threshold:
            return colors[index]
    return colors[-1]


def _default_bin_labels(thresholds):
    labels = [f"< {thresholds[0]:g}"]
    for lower, upper in zip(thresholds, thresholds[1:]):
        labels.append(f"{lower:g} – {upper:g}")
    labels.append(f"≥ {thresholds[-1]:g}")
    return labels


def _render_map_legend(container_id, colors, labels, settings):
    """Absolutely-positioned legend inside the map container."""
    title = settings.get("legend_title") or ""
    rows = "".join(
        f'<div class="odi-legend-row"><span class="odi-legend-swatch" '
        f'style="background:{color}"></span>{html_lib.escape(str(label))}</div>'
        for color, label in zip(colors, labels)
    )
    title_html = (
        f'<div class="odi-legend-title">{html_lib.escape(str(title))}</div>' if title else ""
    )
    return (
        f"<style>"
        f"#{container_id} .odi-legend{{position:absolute;z-index:500;right:10px;bottom:16px;"
        f"background:rgba(255,255,255,.9);padding:6px 8px;border-radius:4px;"
        f"font:12px/1.4 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3);}}"
        f"#{container_id} .odi-legend-title{{font-weight:600;margin-bottom:3px;}}"
        f"#{container_id} .odi-legend-row{{white-space:nowrap;}}"
        f"#{container_id} .odi-legend-swatch{{display:inline-block;width:12px;height:12px;"
        f"margin-right:5px;vertical-align:-1px;border:1px solid rgba(0,0,0,.25);}}"
        f"</style>"
        f'<div class="odi-legend">{title_html}{rows}</div>'
    )


def _format_text_for_map(record, fields):
    if not fields:
        return None
    entries = fields if isinstance(fields, (list, tuple)) else [fields]
    parts = []
    for entry in entries:
        label = key = None
        if isinstance(entry, dict):
            key = entry.get("field") or entry.get("key")
            label = entry.get("label")
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            label, key = entry[0], entry[1]
        else:
            key = entry
        if not key:
            continue
        val = record.get(key)
        if pd.isna(val):
            continue
        parts.append(f"{label}: {val}" if label else str(val))
    return "<br>".join(parts) if parts else None


def _resolve_tile_settings(settings):
    tiles_value = settings.get("tiles", "OpenStreetMap")
    if tiles_value is None or tiles_value is False:
        return None, {}
    if isinstance(tiles_value, str):
        norm = tiles_value.strip().lower()
        if norm in {"none", "off", "false", "0", "no", ""}:
            return None, {}
    if not tiles_value:
        tiles_value = "OpenStreetMap"

    attribution = settings.get("tile_attribution")
    default_attr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    if isinstance(tiles_value, str) and tiles_value == "OpenStreetMap":
        tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    elif isinstance(tiles_value, str) and ("://" in tiles_value or "{z}" in tiles_value):
        tile_url = tiles_value
    else:
        logger.warning("Unsupported tiles value '%s'; falling back to OpenStreetMap.", tiles_value)
        tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    tile_opts = dict(settings.get("tile_options") or {})
    tile_opts.setdefault("attribution", attribution or default_attr)
    return tile_url, tile_opts


def create_chloropleth(data: pd.DataFrame, settings: dict) -> str:
    """Leaflet choropleth map — returns an HTML string (not an ECharts dict)."""
    df = pd.DataFrame(data).copy()

    geojson_obj = settings.get("geojson") or settings.get("geojson_data") or settings.get("geojson_object")
    geojson_path = settings.get("geojson_path") or settings.get("geojson_file")
    data_key = settings.get("data_key") or settings.get("key") or settings.get("id_field") or "id"
    geo_key = settings.get("geo_key") or settings.get("feature_key") or data_key
    value_field = settings.get("value") or settings.get("value_field") or "value"
    geojson_column = settings.get("geojson_column")

    if not geojson_column and isinstance(geojson_obj, str) and geojson_obj in df.columns:
        geojson_column = geojson_obj
        geojson_obj = None

    join_on_index = bool(settings.get("join_on_index", False))
    if join_on_index:
        df = df.reset_index(drop=True)
        df["__index"] = list(range(len(df)))
        data_key = geo_key = "__index"

    if geojson_column and geojson_column in df.columns and data_key not in df.columns:
        df = df.reset_index(drop=True)
        df["__index"] = list(range(len(df)))
        data_key = geo_key = "__index"

    if geojson_column and geojson_column in df.columns:
        features = []
        for idx, record in enumerate(df.to_dict(orient="records")):
            item = record.get(geojson_column)
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except Exception:
                    item = None
            if isinstance(item, dict) and item.get("type") == "FeatureCollection":
                geojson_obj = item
                features = None
                break
            feature = None
            if isinstance(item, dict) and item.get("type") == "Feature":
                feature = dict(item)
            elif isinstance(item, dict) and item.get("type") in {"Polygon", "MultiPolygon"} and "coordinates" in item:
                feature = {"type": "Feature", "properties": {}, "geometry": item}
            if not feature:
                logger.error("Choropleth geojson column row %s is invalid GeoJSON.", idx)
                return '<div class="chart-error">Choropleth GeoJSON column contains invalid geometry.</div>'
            props = feature.get("properties") or {}
            props.setdefault("__index", idx)
            jv = record.get(data_key)
            if jv is not None and not pd.isna(jv):
                props.setdefault(geo_key, jv)
            feature["properties"] = props
            features.append(feature)
        if features is not None:
            geojson_obj = {"type": "FeatureCollection", "features": features}

    if geojson_obj is None and geojson_path:
        try:
            with open(str(geojson_path), encoding="utf-8") as fh:
                geojson_obj = json.load(fh)
        except Exception as exc:
            logger.error("Choropleth failed to load geojson: %s", exc)
            return '<div class="chart-error">Choropleth requires a valid GeoJSON input.</div>'

    if geojson_obj is None:
        return '<div class="chart-error">Choropleth requires GeoJSON input.</div>'
    if isinstance(geojson_obj, str):
        try:
            geojson_obj = json.loads(geojson_obj)
        except Exception:
            return '<div class="chart-error">Choropleth GeoJSON could not be parsed.</div>'

    if data_key not in df.columns:
        return '<div class="chart-error">Choropleth data missing join key. Set join_on_index=true to align rows to polygons.</div>'
    if value_field not in df.columns:
        return '<div class="chart-error">Choropleth data missing value field.</div>'

    df[value_field] = pd.to_numeric(df[value_field], errors="coerce")
    tooltip_spec = settings.get("tooltips") or settings.get("tooltip")
    popup_spec = settings.get("popup")

    payload_by_key: dict = {}
    for record in df.to_dict(orient="records"):
        jv = record.get(data_key)
        if jv is None or pd.isna(jv):
            continue
        val = record.get(value_field)
        payload_by_key[str(jv)] = {
            "value": None if val is None or pd.isna(val) else float(val),
            "tooltip": _format_text_for_map(record, tooltip_spec),
            "popup": _format_text_for_map(record, popup_spec),
        }

    values = [e["value"] for e in payload_by_key.values() if e["value"] is not None]
    colors = settings.get("colors") or ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c"]
    if not isinstance(colors, (list, tuple)) or len(colors) < 2:
        colors = ["#eff3ff", "#6baed6", "#08519c"]
    colors = [str(c) for c in colors]

    try:
        bins = max(2, min(int(settings.get("bins") or settings.get("steps") or len(colors)), len(colors)))
    except Exception:
        bins = len(colors)
    colors = colors[:bins]

    method = (settings.get("method") or settings.get("binning") or "quantile").lower()
    thresholds: list = []
    if values:
        arr = np.asarray(values, dtype=float)
        if method in {"equal", "equal_interval", "interval"}:
            vmin, vmax = float(np.nanmin(arr)), float(np.nanmax(arr))
            if vmax > vmin:
                step = (vmax - vmin) / bins
                thresholds = [vmin + step * i for i in range(1, bins)]
        else:
            try:
                thresholds = [float(v) for v in np.quantile(arr, [i / bins for i in range(1, bins)])]
            except Exception:
                thresholds = []

    missing_color = settings.get("missing_color", "#d9d9d9")
    fill_opacity = settings.get("fill_opacity", 0.75)
    border_color = settings.get("border_color", "#ffffff")
    border_weight = settings.get("border_weight", 1)
    width_css = _css_width(settings.get("width", 700))
    height_css = _css_dimension(settings.get("height", 420), fallback_px=420)

    uid = uuid.uuid4().hex[:8]
    cid = _sanitize_map_identifier(f"{settings.get('map_id') or settings.get('chart_id') or 'choropleth'}_{uid}") or f"choropleth_{uid}"
    map_var = _sanitize_js_identifier(f"map_{cid}")
    layer_var = _sanitize_js_identifier(f"layer_{cid}")

    tile_url, tile_opts = _resolve_tile_settings(settings)
    tile_opts_json = _escape_js(tile_opts or {})

    map_opts = dict(settings.get("map_options") or {})
    map_opts.setdefault("zoomControl", True)
    map_opts.setdefault("scrollWheelZoom", settings.get("scroll_wheel_zoom", True))
    map_opts.setdefault("dragging", settings.get("dragging", True))
    map_opts_json = _escape_js(map_opts)

    zoom = settings.get("zoom_start", 6)
    clat = settings.get("center_lat")
    clon = settings.get("center_lon")
    bg = settings.get("background_color") or settings.get("map_background")
    if bg is None and not tile_url:
        bg = "#ffffff"
    bg_css = f"background:{bg};" if bg else ""

    style_block = f"<style>#{cid}{{width:{width_css};height:{height_css};{bg_css}}}#{cid}.leaflet-container{{{bg_css}}}</style>"
    container_div = f'<div id="{cid}" class="leaflet-map" data-leaflet-map="1" data-markercluster="0"></div>'

    js = ["(function(){",
          f"  var containerId = {_escape_js(cid)};",
          "  var mapEl = document.getElementById(containerId);",
          "  if (!mapEl) { return; }",
          f"  var dataByKey = {_escape_js(payload_by_key)};",
          f"  var geoKey = {_escape_js(geo_key)};",
          f"  var colors = {_escape_js(colors)};",
          f"  var thresholds = {_escape_js(thresholds)};",
          f"  var missingColor = {_escape_js(missing_color)};",
          "  function getColor(v){",
          "    if(v===null||v===undefined||isNaN(v)){return missingColor;}",
          "    for(var i=0;i<thresholds.length;i++){if(v<=thresholds[i])return colors[i];}",
          "    return colors[colors.length-1];",
          "  }",
          "  function style(f){",
          "    var p=(f&&f.properties)?f.properties:{};",
          "    var k=p[geoKey];",
          "    if(k===null||k===undefined)k=(f&&f.id!==null&&f.id!==undefined)?f.id:null;",
          "    var e=(k!==null&&k!==undefined)?dataByKey[String(k)]:null;",
          f"    return{{fillColor:getColor(e?e.value:null),weight:{border_weight},opacity:1,color:{_escape_js(border_color)},fillOpacity:{fill_opacity}}};",
          "  }"]

    if clat is not None and clon is not None:
        try:
            js.append(f"  var {map_var}=L.map(containerId,{map_opts_json}).setView([{float(clat)},{float(clon)}],{int(zoom)});")
            clat = clon = True  # mark as set
        except Exception:
            clat = clon = None

    if clat is None or clon is None:
        js.append(f"  var {map_var}=L.map(containerId,{map_opts_json}).setView([0,0],{int(zoom)});")

    js += ["  window.__leafletMaps=window.__leafletMaps||{};",
           f"  window.__leafletMaps[containerId]={map_var};"]
    if tile_url:
        js.insert(-2, f"  L.tileLayer({_escape_js(tile_url)},{tile_opts_json}).addTo({map_var});")

    if settings.get("control_scale", True):
        js.append(f"  L.control.scale().addTo({map_var});")

    hs = dict(settings.get("highlight_style") or {})
    hs.setdefault("weight", border_weight + 1)
    hs.setdefault("color", "#666666")
    hs.setdefault("fillOpacity", min(1.0, float(fill_opacity) + 0.1))

    js += [f"  var geojsonData={_escape_js(geojson_obj)};",
           "  function onEachFeature(f,layer){",
           "    var p=(f&&f.properties)?f.properties:{};",
           "    var k=p[geoKey];if(k===null||k===undefined)k=(f&&f.id!==null&&f.id!==undefined)?f.id:null;",
           "    var e=(k!==null&&k!==undefined)?dataByKey[String(k)]:null;",
           "    if(e&&e.popup)layer.bindPopup(e.popup);",
           "    if(e&&e.tooltip)layer.bindTooltip(e.tooltip,{sticky:true});",
           "    if((!e||(!e.tooltip&&!e.popup))&&p){",
           "      var lbl=p.name||p[geoKey]||(k!==null?String(k):'');",
           "      var val=e?e.value:null;",
           "      if(lbl){var txt=(val===null||val===undefined||isNaN(val))?(lbl+': n/a'):(lbl+': '+val);layer.bindTooltip(txt,{sticky:true});}",
           "    }",
           f"    layer.on('mouseover',function(){{layer.setStyle({_escape_js(hs)});}});",
           f"    layer.on('mouseout',function(e){{{layer_var}.resetStyle(e.target);}});",
           "  }",
           f"  var {layer_var}=L.geoJSON(geojsonData,{{style:style,onEachFeature:onEachFeature}}).addTo({map_var});"]

    if settings.get("fit_bounds", True) and (clat is None or clon is None):
        fit_js = (
            f"  try{{var b={layer_var}.getBounds();"
            f"if(b&&b.isValid&&b.isValid()){{{map_var}.fitBounds(b,{{padding:[10,10]}});}}"
            f"}}catch(e){{}}"
        )
        js.append(fit_js)

    if settings.get("legend", True):
        lt = _escape_js(str(settings.get("legend_title") or value_field))
        lp = _escape_js(settings.get("legend_position") or "bottomright")
        js += [f"  var legend=L.control({{position:{lp}}});",
               "  legend.onAdd=function(){",
               "    var div=L.DomUtil.create('div','leaflet-legend');",
               "    div.style.cssText='background:rgba(255,255,255,0.9);padding:8px 10px;border-radius:4px;box-shadow:0 0 10px rgba(0,0,0,0.15)';",
               f"    var title={lt};",
               "    if(title){var t=document.createElement('div');t.style.fontWeight='600';t.style.marginBottom='6px';t.textContent=title;div.appendChild(t);}",
               "    function fmt(n){if(n===null||n===undefined||isNaN(n))return 'n/a';try{return Number(n).toLocaleString();}catch(e){return String(n);}}",
               "    for(var i=0;i<colors.length;i++){",
               "      var row=document.createElement('div');row.style.cssText='display:flex;align-items:center;gap:8px';",
               "      var sw=document.createElement('i');sw.style.cssText='width:14px;height:14px;display:inline-block;border:1px solid rgba(0,0,0,0.15)';sw.style.background=colors[i];row.appendChild(sw);",
               "      var lbl=document.createElement('span');",
               "      var from=(i===0)?null:thresholds[i-1];var to=(i<thresholds.length)?thresholds[i]:null;",
               "      if(from===null&&to!==null)lbl.textContent='\\u2264 '+fmt(to);",
               "      else if(from!==null&&to!==null)lbl.textContent=fmt(from)+' \\u2013 '+fmt(to);",
               "      else if(from!==null&&to===null)lbl.textContent='\\u2265 '+fmt(from);",
               "      row.appendChild(lbl);div.appendChild(row);",
               "    }",
               "    return div;",
               "  };",
               f"  legend.addTo({map_var});"]

    js += ["  if(!window.__leafletMapResizeHook){",
           "    window.__leafletMapResizeHook=true;",
           "    document.addEventListener('shown.bs.tab',function(){Object.values(window.__leafletMaps||{}).forEach(function(m){m.invalidateSize();});});",
           "    document.addEventListener('shown.bs.collapse',function(){Object.values(window.__leafletMaps||{}).forEach(function(m){m.invalidateSize();});});",
           "  }",
           f"  setTimeout(function(){{if(window.__leafletMaps&&window.__leafletMaps[containerId])window.__leafletMaps[containerId].invalidateSize();}},50);",
           "})();"]

    return "\n".join([style_block, container_div, f"<script>\n{chr(10).join(js)}\n</script>"])


def create_map_markers(data, settings: dict) -> str:
    """Leaflet marker map — returns an HTML string (not an ECharts dict)."""
    df = pd.DataFrame(data).copy()
    lat_field = settings.get("latitude") or settings.get("lat") or settings.get("y")
    lon_field = settings.get("longitude") or settings.get("lon") or settings.get("x")

    if not lat_field or not lon_field:
        return '<div class="chart-error">Map markers require latitude/longitude fields.</div>'
    if lat_field not in df.columns or lon_field not in df.columns:
        return '<div class="chart-error">Map markers data missing latitude/longitude fields.</div>'

    df[lat_field] = pd.to_numeric(df[lat_field], errors="coerce")
    df[lon_field] = pd.to_numeric(df[lon_field], errors="coerce")
    df = df.dropna(subset=[lat_field, lon_field])
    if df.empty:
        return '<div class="chart-error">No valid coordinates for map markers.</div>'

    clat = settings.get("center_lat")
    clon = settings.get("center_lon")
    try:
        clat = float(clat) if clat is not None and not pd.isna(clat) else float(df[lat_field].mean())
        clon = float(clon) if clon is not None and not pd.isna(clon) else float(df[lon_field].mean())
    except Exception:
        clat, clon = float(df[lat_field].iloc[0]), float(df[lon_field].iloc[0])

    width_css = _css_width(settings.get("width", 700))
    height_css = _css_dimension(settings.get("height", 400), fallback_px=400)

    uid = uuid.uuid4().hex[:8]
    cid = _sanitize_map_identifier(f"{settings.get('map_id') or settings.get('chart_id') or 'map'}_{uid}") or f"map_{uid}"
    map_var = _sanitize_js_identifier(f"map_{cid}")
    cluster_var = _sanitize_js_identifier(f"cluster_{cid}")

    tile_url, tile_opts = _resolve_tile_settings(settings)
    tile_opts_json = _escape_js(tile_opts or {})
    map_opts = dict(settings.get("map_options") or {})
    map_opts.setdefault("zoomControl", True)
    map_opts.setdefault("scrollWheelZoom", settings.get("scroll_wheel_zoom", True))
    map_opts.setdefault("dragging", settings.get("dragging", True))
    map_opts_json = _escape_js(map_opts)

    marker_style = (settings.get("marker_style") or "marker").lower()
    marker_color_field = settings.get("marker_color") or settings.get("color")
    # Optional value->colour binning. Without it the field is still read as a literal
    # colour string, so existing map graphics keep working unchanged.
    try:
        bin_spec = _parse_color_bins(settings.get("color_bins"))
    except ValueError as exc:
        return f'<div class="chart-error">Invalid color_bins: {html_lib.escape(str(exc))}</div>'
    bin_thresholds = bin_colors = bin_labels = None
    if bin_spec:
        bin_thresholds, bin_colors, bin_labels = bin_spec
    tooltip_spec = settings.get("tooltips") or settings.get("tooltip")
    popup_spec = settings.get("popup")
    tooltip_sticky = settings.get("tooltip_sticky", True)
    cluster_enabled = bool(settings.get("cluster", False))
    cluster_circles = cluster_enabled and marker_style != "circle"

    bg = settings.get("background_color") or settings.get("map_background")
    if bg is None and not tile_url:
        bg = "#ffffff"
    bg_css = f"background:{bg};" if bg else ""

    style_block = f"<style>#{cid}{{width:{width_css};height:{height_css};{bg_css}}}#{cid}.leaflet-container{{{bg_css}}}</style>"
    container_div = f'<div id="{cid}" class="leaflet-map" data-leaflet-map="1" data-markercluster="{int(cluster_circles)}"></div>'

    # Legend lives in a positioned wrapper around the map, not inside the Leaflet
    # container, which Leaflet manages and re-renders.
    legend_requested = settings.get("legend", bool(bin_thresholds is not None))
    if legend_requested and bin_thresholds is not None:
        wrap_id = f"{cid}_wrap"
        labels = bin_labels or _default_bin_labels(bin_thresholds)
        style_block += (
            f"<style>#{wrap_id}{{position:relative;display:inline-block;"
            f"width:{width_css};}}</style>"
        )
        container_div = (
            f'<div id="{wrap_id}" class="odi-map-wrap">'
            f"{container_div}"
            f"{_render_map_legend(wrap_id, bin_colors, labels, settings)}"
            f"</div>"
        )

    js = ["(function(){",
          f"  var containerId={_escape_js(cid)};",
          "  var mapEl=document.getElementById(containerId);if(!mapEl)return;",
          f"  var {map_var}=L.map(containerId,{map_opts_json}).setView([{clat},{clon}],{settings.get('zoom_start',11)});"]

    if tile_url:
        js.append(f"  L.tileLayer({_escape_js(tile_url)},{tile_opts_json}).addTo({map_var});")
    js += ["  window.__leafletMaps=window.__leafletMaps||{};",
           f"  window.__leafletMaps[containerId]={map_var};"]
    if settings.get("control_scale", True):
        js.append(f"  L.control.scale().addTo({map_var});")
    if cluster_circles:
        js.append(f"  var {cluster_var}=L.markerClusterGroup();")

    for record in df.to_dict(orient="records"):
        lat = record.get(lat_field)
        lon = record.get(lon_field)
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue
        try:
            lat, lon = float(lat), float(lon)
        except Exception:
            continue
        popup_text = _format_text_for_map(record, popup_spec)
        tooltip_text = _format_text_for_map(record, tooltip_spec)

        if marker_style == "circle":
            ck = {"radius": settings.get("radius", 6), "fillOpacity": settings.get("fill_opacity", 0.7), "opacity": settings.get("line_opacity", 0.9)}
            # Leaflet defaults to a 3px stroke, which dominates small radii and
            # inflates apparent marker size. Only emitted when set, so existing
            # map graphics render exactly as before.
            if settings.get("weight") is not None:
                ck["weight"] = settings["weight"]
            if settings.get("stroke") is False:
                ck["stroke"] = False
            cc = record.get(marker_color_field) if marker_color_field else None
            if bin_thresholds is not None:
                cc = _color_for_value(cc, bin_thresholds, bin_colors)
            if cc is not None and not pd.isna(cc) and cc != "":
                ck["color"] = ck["fillColor"] = str(cc)
            elif settings.get("circle_color"):
                ck["color"] = ck["fillColor"] = settings["circle_color"]
            js.append(f"  var marker=L.circleMarker([{lat},{lon}],{_escape_js(ck)});")
        else:
            js.append(f"  var marker=L.marker([{lat},{lon}]);")

        if popup_text:
            js.append(f"  marker.bindPopup({_escape_js(popup_text)});")
        if tooltip_text:
            js.append(f"  marker.bindTooltip({_escape_js(tooltip_text)},{'{sticky:true}' if tooltip_sticky else '{}'});")
        js.append(f"  {''+cluster_var+'.addLayer(marker)' if cluster_circles else 'marker.addTo('+map_var+')'};")

    if cluster_circles:
        js.append(f"  {map_var}.addLayer({cluster_var});")

    js += ["  if(!window.__leafletMapResizeHook){",
           "    window.__leafletMapResizeHook=true;",
           "    document.addEventListener('shown.bs.tab',function(){Object.values(window.__leafletMaps||{}).forEach(function(m){m.invalidateSize();});});",
           "    document.addEventListener('shown.bs.collapse',function(){Object.values(window.__leafletMaps||{}).forEach(function(m){m.invalidateSize();});});",
           "  }",
           f"  setTimeout(function(){{if(window.__leafletMaps&&window.__leafletMaps[containerId])window.__leafletMaps[containerId].invalidateSize();}},50);",
           "})();"]

    return "\n".join([style_block, container_div, f"<script>\n{chr(10).join(js)}\n</script>"])
