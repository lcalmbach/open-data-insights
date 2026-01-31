from __future__ import annotations
import base64
import json
import logging
import re
import uuid
from io import BytesIO
from typing import List

import numpy as np
import pandas as pd
import altair as alt
from wordcloud import WordCloud


logger = logging.getLogger(__name__)



def generate_chart(data, settings, chart_id):
    """
    Generate a chart based on data and settings and return HTML.
    Uses Altair for most chart types and `wordcloud` for word clouds.
    """
    try:
        chart_functions = {
            "line": create_line_chart,
            "bar": create_bar_chart,
            "bar_stacked": create_bar_stacked_chart,
            "bar-stacked": create_bar_stacked_chart,
            "horizontal_bar": create_horizontal_bar_chart,
            "bar-horizontal": create_horizontal_bar_chart,
            "area": create_area_chart,
            "point": create_point_chart,
            "scatter": create_point_chart,
            "pie": create_pie_chart,
            "heatmap": create_heatmap,
            "histogram": create_histogram,
            "map-markers": create_map_markers,
            "wordcloud": create_word_cloud
        }
        chart_settings = settings.copy() if hasattr(settings, "copy") else dict(settings)
        chart_settings.setdefault("chart_id", chart_id)
        chart_type = chart_settings.get("type").value.lower()
        chart_func = chart_functions.get(chart_type, create_line_chart)
        chart = chart_func(data, chart_settings)

        if chart_type not in ("wordcloud", "map_markers", "map-markers"):
            html = chart.to_html(
                embed_options={
                    "actions": False,  # Hide download buttons
                    "renderer": "svg",  # SVG is better for print/static content
                    "theme": settings.get("theme", "default"),
                }
            )

            html = html.replace('id="vis"', f'id="{chart_id}"')
            html = html.replace('vegaEmbed("#vis"', f'vegaEmbed("#{chart_id}"')
            embed_hook = ".then(function(result) {"
            if embed_hook in html:
                store_view = (
                    "window.__vegaViews = window.__vegaViews || {};\n"
                    f'window.__vegaViews["{chart_id}"] = result.view;'
                )
                html = html.replace(embed_hook, f"{embed_hook}\n{store_view}")
        else:
            html = chart  # wordcloud returns HTML directly
        return html

    except Exception as e:
        logger.error(f"Error generating chart: {str(e)}")
        return f'<div id=\"{chart_id}\" class=\"chart-error\">Error generating chart: {str(e)}</div>'


def create_line_chart(data, settings):
    """Create a line chart with the given data and settings"""
    data[settings['y']] = pd.to_numeric(data[settings['y']], errors='coerce')
    if settings.get('x_type') == "T":
        data[settings.get('x')] = pd.to_datetime(data[settings.get('x')], errors='coerce')
    
    if "focus_line" in settings:
        focus_year = settings["focus_line"]["color_value"]
        settings["x_type"] = 'N'
        base = alt.Chart().encode(
            #x=alt.X("month:O", title="Monat", sort=list(range(1, 13))),
            #y=alt.Y("avg_temp:Q", title="Monatsmittel Temperatur (°C)"),
            x=alt.X(f'{settings["x"]}:{settings["x_type"]}'),
            y=alt.Y(settings["y"]),
            tooltip=settings["tooltips"],
        )
        
        ref_lines = base.transform_filter(
            alt.datum.Year != focus_year
        ).mark_line(
            color=settings["bg_line"]["line_color"],
            strokeWidth=1,
            opacity=0.6
        ).encode(
            detail="Year:N"     # sorgt für eine Linie pro Jahr, ohne Legend
        )

        # Fokusjahr: rot + fett
        focus_line = base.transform_filter(
            alt.datum.Year == focus_year
        ).mark_line(
            color=settings["focus_line"]["line_color"],
            strokeWidth=settings["focus_line"]["line_width"],
        )

        chart = alt.layer(
            ref_lines,
            focus_line,
            data=data   # df = Ergebnis deines SQL-Queries als DataFrame
        ).properties(
            width=700,
            height=380
        )
    else:
        chart = alt.Chart(data).mark_line(
            point=settings.get('show_points', False),
            interpolate=settings.get('interpolate', 'linear')
        )
        # Apply encodings and properties
        chart = apply_common_settings(chart, settings)

    # Line-specific settings
    if 'stroke_width' in settings:
        chart = chart.mark_line(strokeWidth=settings['stroke_width'])
        
    return chart


def create_bar_chart(data, settings):
    """Create a bar chart with the given data and settings"""
    # Determine fields
    x_field = settings.get('x')
    y_field = settings.get('y')
    x_format = settings.get('x_format')
    x_label_angle = settings.get('x_label_angle')
    color_field = settings.get('color')

    # sensible defaults for bar sizing
    total_plot_width = settings.get('plot_width') or settings.get('width') or 700
    min_bar_width = settings.get('bar_min_width', 8)
    max_bar_width = settings.get('bar_max_width', 120)

    # compute number of distinct bars and size (wider when fewer bars, narrower when many)
    try:
        n_bars = int(data[x_field].nunique()) if x_field else 1
    except Exception:
        n_bars = 1
    if n_bars > 0:
        computed_size = int(max(min_bar_width, min(max_bar_width, (int(total_plot_width) / max(1, n_bars)) * 0.9)))
    else:
        computed_size = int(max(min_bar_width, min(max_bar_width, 20)))

    # Build base chart with explicit size
    chart = alt.Chart(data).mark_bar(
        size=computed_size,
        cornerRadiusTopLeft=settings.get('corner_radius', 0),
        cornerRadiusTopRight=settings.get('corner_radius', 0)
    )

    # helper to build an ordered category list so Altair treats x as ordinal (no fractional ticks)
    def _sorted_category_list(values):
        vals = list(values)
        try:
            ints = [int(v) for v in vals]
            if all(float(i) == float(v) for i, v in zip(ints, vals)):
                return [str(i) for i in sorted(set(ints))]
        except Exception:
            pass
        return [str(v) for v in sorted(set(vals), key=lambda x: str(x))]

    x_sort = None
    if x_field:
        try:
            unique_vals = data[x_field].dropna().unique()
            x_sort = _sorted_category_list(unique_vals)
        except Exception:
            x_sort = None

    # Build encodings, force x to ordinal categories to avoid numeric fractional ticks for years
    # Build X axis (format belongs to Axis, NOT to alt.X)
    encodings = {}
    axis_kwargs = {}
    if x_label_angle is not None:
        axis_kwargs["labelAngle"] = x_label_angle
        axis_kwargs["labelOverlap"] = False
    else:
        axis_kwargs["labelAngle"] = 0

    if x_format:
        axis_kwargs["format"] = x_format  # e.g. "%Y-%m" for temporal dates

    axis = alt.Axis(**axis_kwargs)

    x_encoding_kwargs = {
        "title": settings.get("x_title", x_field),
        "axis": axis,
    }
    if x_sort:
        x_encoding_kwargs["sort"] = x_sort

    # Decide type: use temporal when formatting dates; otherwise keep ordinal behavior
    x_type = settings.get("x_type")  # optional explicit override: "T", "O", "Q", "N"
    if not x_type:
        x_type = "T" if x_format else "O"

    encodings["x"] = alt.X(f"{x_field}:{x_type}", **x_encoding_kwargs)

    # Y axis
    if y_field:
        encodings["y"] = alt.Y(y_field, title=settings.get("y_title", y_field))
    else:
        encodings["y"] = alt.Y("count()", title=settings.get("y_title", "count"))

    # Color
    if color_field:
        encodings["color"] = alt.Color(
            color_field,
            scale=alt.Scale(scheme=settings.get("color_scheme", "category10")),
        )

    # Tooltip support
    tooltip = settings.get("tooltip")
    if tooltip:
        encodings["tooltip"] = tooltip
    else:
        tt = []
        if x_field:
            # if x is temporal and you want the same formatting in tooltip, you can do:
            # tt.append(alt.Tooltip(f"{x_field}:T", format=x_format) if x_type == "T" and x_format else x_field)
            tt.append(x_field)
        if y_field:
            tt.append(y_field)
        if color_field:
            tt.append(color_field)
        if tt:
            encodings["tooltip"] = tt

    chart = chart.encode(**encodings)

    # Horizontal bars: swap axes encoding
    if settings.get('horizontal', False):
        # swap x and y encoding by re-encoding
        swapped = {}
        if 'x' in encodings:
            swapped['y'] = encodings['x']
        if 'y' in encodings:
            swapped['x'] = encodings['y']
        if 'color' in encodings:
            swapped['color'] = encodings['color']
        if 'tooltip' in encodings:
            swapped['tooltip'] = encodings['tooltip']
        chart = chart.encode(**swapped)

    # Apply chart properties (title/height/width)
    props = {}
    if 'title' in settings:
        props['title'] = settings['title']
    props['height'] = settings.get('height', 300)
    props['width'] = settings.get('width', 'container')
    chart = chart.properties(**props)

    return chart


def create_horizontal_bar_chart(data, settings):
    """Create a horizontal bar chart by forcing the horizontal flag before delegating."""
    if hasattr(settings, "copy"):
        horizontal_settings = settings.copy()
    else:
        horizontal_settings = dict(settings)
    horizontal_settings["horizontal"] = True
    return create_bar_chart(data, horizontal_settings)


def create_bar_stacked_chart(data, settings):
    """Create a stacked bar chart with the given data and settings"""
    # Decide bar pixel size based on number of distinct bars (x values)
    x_field = settings.get('x')
    # sensible defaults
    total_plot_width = settings.get('plot_width') or settings.get('width') or 700
    min_bar_width = settings.get('bar_min_width', 6)
    max_bar_width = settings.get('bar_max_width', 60)

    try:
        n_bars = int(data[x_field].nunique())
    except Exception:
        n_bars = 1

    # compute ideal bar width: fraction of available width per bar, clamped
    # the factor 0.8 leaves small gaps between bars
    if n_bars > 0:
        computed_size = int(max(min_bar_width, min(max_bar_width, (int(total_plot_width) / n_bars) * 0.8)))
    else:
        computed_size = int(max(min_bar_width, min(max_bar_width, 20)))

    chart = alt.Chart(data).mark_bar(
        size=computed_size,
        cornerRadiusTopLeft=settings.get('corner_radius', 0),
        cornerRadiusTopRight=settings.get('corner_radius', 0)
    )
    
    # Get fields
    y_field = settings.get('y')
    color_field = settings.get('color')
    
    if not x_field or not y_field or not color_field:
        logger.error("Stacked bar chart requires 'x', 'y', and 'color' fields")
        return alt.Chart(data).mark_point()  # Return empty chart
    
    # decide x axis type (O for ordinal, O for quantitative)
    x_type = (settings.get('x_type') or 'O').upper()
    
    # Create stacked encoding
    encodings = {
        'x': alt.X(
            f"{x_field}:{x_type}",
            title=settings.get('x_title', x_field)
        ),
        'y': alt.Y(
            y_field, 
            title=settings.get('y_title', y_field),
            stack=True
        ),
        'color': alt.Color(
            color_field,
            title=settings.get('color_title', color_field),
            scale=alt.Scale(scheme=settings.get('color_scheme', 'category10'))
        )
    }
    
    # Add tooltip
    if settings.get('show_tooltip', True):
        encodings['tooltip'] = settings.get('tooltips')
    
    # Apply encodings
    chart = chart.encode(**encodings)
    
    # Apply percentage normalization if requested
    if settings.get('percentage', False):
        chart = chart.encode(
            y=alt.Y(y_field, stack='normalize', axis=alt.Axis(format='%'))
        )
    
    # Set properties
    props = {}
    if 'title' in settings:
        props['title'] = settings['title']
    props['height'] = settings.get('height', 300)
    props['width'] = settings.get('width', 'container')
    
    chart = chart.properties(**props)
    
    # Add legend configuration if specified
    if 'legend_orient' in settings:
        chart = chart.configure_legend(
            orient=settings['legend_orient'],
            titleFontSize=settings.get('legend_title_font_size', 12),
            labelFontSize=settings.get('legend_label_font_size', 11)
        )
    
    return chart


def create_area_chart(data, settings):
    """Create an area chart with the given data and settings"""
    # Create base chart
    chart = alt.Chart(data).mark_area(
        opacity=settings.get('opacity', 0.6),
        interpolate=settings.get('interpolate', 'linear')
    )
    
    # Apply encodings and properties
    chart = apply_common_settings(chart, settings)
    
    # Area-specific settings
    if settings.get('stacked', True):
        # Use stack='normalize' for percentage stacking
        stack_type = 'normalize' if settings.get('percentage', False) else True
        if 'y' in chart.encoding:
            chart = chart.encode(y=alt.Y(chart.encoding.y.field, stack=stack_type))
    
    return chart


def create_point_chart(data, settings):
    """Create a scatter/point chart with the given data and settings"""
    # Create base chart
    chart = alt.Chart(data).mark_point(
        size=settings.get('point_size', 60),
        filled=settings.get('filled', True),
        opacity=settings.get('opacity', 0.7)
    )
    
    # Apply encodings and properties
    chart = apply_common_settings(chart, settings)
    
    # Point-specific settings
    if 'size' in settings:
        size_field = settings['size']
        chart = chart.encode(size=size_field)
    
    # Add tooltip with multiple fields if specified
    if 'tooltip' in settings:
        tooltip_fields = settings['tooltip']
        if isinstance(tooltip_fields, list):
            chart = chart.encode(tooltip=tooltip_fields)
    
    return chart


def create_pie_chart(data, settings):
    """Create a pie chart with the given data and settings"""
    # For pie charts, we need theta and color encodings
    theta_field = settings.get('theta', settings.get('y'))
    color_field = settings.get('color', settings.get('x'))
    
    if not theta_field or not color_field:
        logger.error("Pie chart requires 'theta' (or 'y') and 'color' (or 'x') fields")
        return alt.Chart(data).mark_point()  # Return empty chart
    
    # Create the pie chart
    chart = alt.Chart(data).mark_arc(
        innerRadius=settings.get('inner_radius', 0),
        outerRadius=settings.get('outer_radius', 100)
    ).encode(
        theta=theta_field,
        color=color_field
    )
    
    # Set properties
    props = {}
    if 'title' in settings:
        props['title'] = settings['title']
    props['height'] = settings.get('height', 300)
    props['width'] = settings.get('width', 300)  # Square for pie charts
    
    chart = chart.properties(**props)
    
    return chart


def create_heatmap(data, settings):
    """Create a heatmap with the given data and settings"""
    # Create base chart
    chart = alt.Chart(data).mark_rect()
    
    # Heatmap requires x, y, and color
    x_field = settings.get('x')
    y_field = settings.get('y')
    color_field = settings.get('color')
    
    if not x_field or not y_field or not color_field:
        logger.error("Heatmap requires 'x', 'y', and 'color' (or 'z') fields")
        return alt.Chart(data).mark_point()  # Return empty chart
    
    # build x encoding as ORDINAL with an explicit sort/domain so Altair won't render
    # numeric axis ticks like 2020, 2020.5, 2021. Convert categories to ints when
    # all values are integer-like, otherwise keep string categories.
    x_unique = []
    try:
        x_unique = list(data[x_field].dropna().unique())
    except Exception:
        x_unique = []

    def _sorted_category_list(values: List) -> List:
        # try integer sort first
        try:
            ints = [int(v) for v in values]
            # ensure roundtrip preserves ordering (guard against floats like 2021.5)
            if all(float(i) == float(v) for i, v in zip(ints, values)):
                return [str(i) for i in sorted(set(ints))]
        except Exception:
            pass
        # fallback: string sort stable
        return [str(v) for v in sorted(set(values), key=lambda x: (str(x)))]

    x_sort = _sorted_category_list(x_unique) if x_unique else None
    if x_sort:
        x_enc = alt.X(f"{x_field}:O", title=settings.get("x_title", x_field), sort=x_sort, axis=alt.Axis(labelAngle=0))
    else:
        x_enc = alt.X(f"{x_field}:O", title=settings.get("x_title", x_field), axis=alt.Axis(labelAngle=0))

    # allow y domain from settings: prefer explicit y_domain, fallback to generic domain
    domain = settings.get('y_domain', settings.get('domain'))
    if domain is not None:
        y_enc = alt.Y(
            f'{y_field}:O',
            title=settings.get('y_title', y_field),
            sort='descending'
        )
    else:
        y_enc = alt.Y(f"{y_field}:O", title=settings.get("y_title", y_field), sort='descending')

    # Encode color
    # Only include domain in the scale when it is provided (Altair/vega rejects None)
    color_scale_kwargs = {"scheme": settings.get("color_scheme", "viridis")}
    color_domain = settings.get("color_domain")
    if color_domain is not None:
        color_scale_kwargs["domain"] = color_domain
    
    color_enc = alt.Color(
        f'{color_field}:Q',

    )
    
    chart = (
        alt.Chart(data)
        .mark_rect()
        .encode(
            x=x_enc,
            y=y_enc,
            color=color_enc,
            tooltip=[f"{x_field}:O", f"{y_field}:O", f"{color_field}:Q"]
        )
        .properties(width=settings.get("width", 700), height=settings.get("height", {'step': 18}), title=settings.get("title", "Heatmap"))
    )
    
    # optional tooltip
    if settings.get('show_tooltip', True):
        chart = chart.encode(tooltip=[x_field, y_field, color_field])
    
    # Set properties
    props = {}
    if 'title' in settings:
        props['title'] = settings['title']
    props['height'] = settings.get('height', 300)
    props['width'] = settings.get('width', 'container')
    
    chart = chart.properties(**props)
    
    return chart


def _sanitize_map_identifier(identifier):
    """Turn an arbitrary identifier into a JS-friendly map name."""
    if not identifier:
        return None
    identifier = str(identifier)
    sanitized = re.sub(r"[^0-9a-zA-Z_]", "_", identifier)
    if not sanitized:
        return None
    if not (sanitized[0].isalpha() or sanitized[0] == "_"):
        sanitized = "_" + sanitized
    return sanitized


def _sanitize_js_identifier(identifier):
    sanitized = _sanitize_map_identifier(identifier)
    return sanitized or "_map"


def _css_dimension(value, *, fallback_px=400, default_unit="px"):
    if value is None:
        return f"{fallback_px}{default_unit}"
    if isinstance(value, (int, float)):
        return f"{int(value)}{default_unit}"
    text = str(value).strip()
    if text.lower() in {"container", "100%"}:
        return f"{fallback_px}{default_unit}"
    return text


def _css_width(value):
    if value is None:
        return "100%"
    if isinstance(value, (int, float)):
        return f"{int(value)}px"
    text = str(value).strip()
    if text.lower() == "container":
        return "100%"
    return text


def _escape_js(value):
    if value is None:
        return "null"
    return json.dumps(value)


def _format_text_for_map(record, fields):
    if not fields:
        return None
    entries = fields if isinstance(fields, (list, tuple)) else [fields]
    values = []
    for entry in entries:
        label = None
        key = None
        if isinstance(entry, dict):
            key = entry.get("field") or entry.get("key")
            label = entry.get("label")
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            label = entry[0]
            key = entry[1]
        else:
            key = entry
        if not key:
            continue
        val = record.get(key)
        if pd.isna(val):
            continue
        text = str(val)
        if label:
            values.append(f"{label}: {text}")
        else:
            values.append(text)
    if not values:
        return None
    return "<br>".join(values)


def _resolve_tile_settings(settings):
    tiles_value = settings.get("tiles") or "OpenStreetMap"
    tile_attribution = settings.get("tile_attribution")
    default_attribution = (
        '&copy; <a href="https://www.openstreetmap.org/copyright">'
        "OpenStreetMap</a> contributors"
    )
    if isinstance(tiles_value, str) and tiles_value == "OpenStreetMap":
        tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        tile_attribution = tile_attribution or default_attribution
    elif isinstance(tiles_value, str) and (
        "://" in tiles_value or "{z}" in tiles_value or "{x}" in tiles_value
    ):
        tile_url = tiles_value
        tile_attribution = tile_attribution or default_attribution
    else:
        logger.warning("Unsupported tiles value '%s'; defaulting to OpenStreetMap.", tiles_value)
        tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        tile_attribution = tile_attribution or default_attribution

    tile_options = settings.get("tile_options") or {}
    if not isinstance(tile_options, dict):
        tile_options = {}
    if "attribution" not in tile_options:
        tile_options["attribution"] = tile_attribution
    return tile_url, tile_options


def create_map_markers(data, settings):
    """Create a Leaflet map populated with markers or circle markers."""

    df = pd.DataFrame(data).copy()

    lat_field = (
        settings.get("latitude")
        or settings.get("lat")
        or settings.get("y")
    )
    lon_field = (
        settings.get("longitude")
        or settings.get("lon")
        or settings.get("x")
    )

    if not lat_field or not lon_field:
        logger.error("Map markers requires 'latitude' and 'longitude' fields.")
        return '<div class="chart-error">Map markers require latitude/longitude fields.</div>'

    if lat_field not in df.columns or lon_field not in df.columns:
        logger.error("Map markers data missing latitude or longitude columns.")
        return '<div class="chart-error">Map markers data missing latitude/longitude fields.</div>'

    df[lat_field] = pd.to_numeric(df[lat_field], errors="coerce")
    df[lon_field] = pd.to_numeric(df[lon_field], errors="coerce")

    df = df.dropna(subset=[lat_field, lon_field])
    if df.empty:
        logger.warning("Map markers chart has no valid coordinates.")
        return '<div class="chart-error">No valid coordinates for map markers.</div>'

    center_lat = settings.get("center_lat")
    center_lon = settings.get("center_lon")
    if center_lat is None or pd.isna(center_lat):
        center_lat = df[lat_field].mean()
    if center_lon is None or pd.isna(center_lon):
        center_lon = df[lon_field].mean()
    try:
        center_lat = float(center_lat)
        center_lon = float(center_lon)
    except Exception:
        logger.warning("Map center could not be parsed; using first coordinate.")
        center_lat = float(df[lat_field].iloc[0])
        center_lon = float(df[lon_field].iloc[0])

    width = settings.get("width", 700)
    height = settings.get("height", 400)
    height_css = _css_dimension(height, fallback_px=400)
    width_css = _css_width(width)

    map_id = settings.get("map_id") or settings.get("chart_id") or "map"
    base_id = _sanitize_map_identifier(map_id) or "map"
    unique_suffix = uuid.uuid4().hex[:8]
    container_id = f"{base_id}_{unique_suffix}"
    container_id = _sanitize_map_identifier(container_id) or f"map_{unique_suffix}"
    map_var = _sanitize_js_identifier(f"map_{container_id}")
    cluster_var = _sanitize_js_identifier(f"cluster_{container_id}")

    tile_url, tile_options = _resolve_tile_settings(settings)
    try:
        tile_options_json = _escape_js(tile_options)
    except Exception:
        logger.warning("Tile options could not be serialized; using attribution only.")
        tile_options_json = _escape_js({"attribution": tile_options.get("attribution")})

    map_options = settings.get("map_options") or {}
    if not isinstance(map_options, dict):
        map_options = {}
    if "zoomControl" not in map_options:
        map_options["zoomControl"] = True
    if "scrollWheelZoom" not in map_options:
        map_options["scrollWheelZoom"] = settings.get("scroll_wheel_zoom", True)
    if "dragging" not in map_options:
        map_options["dragging"] = settings.get("dragging", True)
    try:
        map_options_json = _escape_js(map_options)
    except Exception:
        logger.warning("Map options could not be serialized; using defaults.")
        map_options_json = "{}"

    marker_style = (settings.get("marker_style") or "marker").lower()
    marker_color_field = settings.get("marker_color") or settings.get("color")
    tooltip_spec = settings.get("tooltips") or settings.get("tooltip")
    popup_spec = settings.get("popup")
    tooltip_sticky = settings.get("tooltip_sticky", True)
    cluster_enabled = bool(settings.get("cluster", False))
    cluster_circles = cluster_enabled and marker_style != "circle"
    if cluster_enabled and marker_style == "circle":
        logger.info("Map marker clustering enabled, but circle markers are not clustered.")
    icon_name = settings.get("icon") or settings.get("icon_name")
    icon_color = settings.get("icon_color")
    if (icon_name or icon_color) and marker_style != "circle":
        logger.info("Leaflet icon customization requires extra plugins; using default icons.")

    style_block = f"<style>#{container_id}{{width:{width_css};height:{height_css};}}</style>"
    container_div = (
        f'<div id="{container_id}" class="leaflet-map" '
        f'data-leaflet-map="1" data-markercluster="{int(cluster_circles)}"></div>'
    )

    js_lines = [
        "(function(){",
        f"  var containerId = {_escape_js(container_id)};",
        "  var mapEl = document.getElementById(containerId);",
        "  if (!mapEl) { return; }",
        f"  var {map_var} = L.map(containerId, {map_options_json}).setView("
        f"[{center_lat}, {center_lon}], {settings.get('zoom_start', 11)});",
        f"  L.tileLayer({_escape_js(tile_url)}, {tile_options_json}).addTo({map_var});",
        "  window.__leafletMaps = window.__leafletMaps || {};",
        f"  window.__leafletMaps[containerId] = {map_var};",
    ]

    if settings.get("control_scale", True):
        js_lines.append(f"  L.control.scale().addTo({map_var});")

    if cluster_circles:
        js_lines.append(f"  var {cluster_var} = L.markerClusterGroup();")

    for record in df.to_dict(orient="records"):
        lat = record.get(lat_field)
        lon = record.get(lon_field)
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except Exception:
            continue

        popup_text = _format_text_for_map(record, popup_spec)
        tooltip_text = _format_text_for_map(record, tooltip_spec)

        if marker_style == "circle":
            circle_kwargs = {
                "radius": settings.get("radius", 6),
                "fillOpacity": settings.get("fill_opacity", 0.7),
                "opacity": settings.get("line_opacity", 0.9),
            }
            coord_color = record.get(marker_color_field) if marker_color_field else None
            if coord_color and not pd.isna(coord_color):
                circle_kwargs["color"] = str(coord_color)
                circle_kwargs["fillColor"] = str(coord_color)
            elif settings.get("circle_color"):
                circle_kwargs["color"] = settings["circle_color"]
                circle_kwargs["fillColor"] = settings["circle_color"]
            circle_kwargs_json = _escape_js(circle_kwargs)
            js_lines.append(
                f"  var marker = L.circleMarker([{lat}, {lon}], {circle_kwargs_json});"
            )
        else:
            js_lines.append(f"  var marker = L.marker([{lat}, {lon}]);")

        if popup_text:
            js_lines.append(f"  marker.bindPopup({_escape_js(popup_text)});")
        if tooltip_text:
            sticky_opt = "{sticky:true}" if tooltip_sticky else "{}"
            js_lines.append(
                f"  marker.bindTooltip({_escape_js(tooltip_text)}, {sticky_opt});"
            )

        if cluster_circles:
            js_lines.append(f"  {cluster_var}.addLayer(marker);")
        else:
            js_lines.append(f"  marker.addTo({map_var});")

    if cluster_circles:
        js_lines.append(f"  {map_var}.addLayer({cluster_var});")

    js_lines.extend(
        [
            "  if (!window.__leafletMapResizeHook) {",
            "    window.__leafletMapResizeHook = true;",
            "    document.addEventListener('shown.bs.tab', function(){",
            "      Object.values(window.__leafletMaps || {}).forEach(function(map){",
            "        map.invalidateSize();",
            "      });",
            "    });",
            "    document.addEventListener('shown.bs.collapse', function(){",
            "      Object.values(window.__leafletMaps || {}).forEach(function(map){",
            "        map.invalidateSize();",
            "      });",
            "    });",
            "  }",
            "  setTimeout(function(){",
            f"    if (window.__leafletMaps && window.__leafletMaps[containerId]) {{",
            "      window.__leafletMaps[containerId].invalidateSize();",
            "    }",
            "  }, 50);",
            "})();",
        ]
    )

    script_block = "<script>\n" + "\n".join(js_lines) + "\n</script>"

    return "\n".join([style_block, container_div, script_block])


def create_histogram(data, settings):
    """Create a histogram by pre-binning the data with numpy."""
    x_field = settings.get("x")
    if not x_field:
        logger.error("Histogram requires an 'x' field to bin.")
        return alt.Chart(pd.DataFrame({"count": []})).mark_bar()

    df = pd.DataFrame(data).copy()
    if x_field not in df.columns:
        logger.error("Histogram field '%s' not in data columns.", x_field)
        return alt.Chart(pd.DataFrame({"count": []})).mark_bar()

    x_values = pd.to_numeric(df[x_field], errors="coerce").dropna().to_numpy()
    if x_values.size == 0:
        logger.warning("Histogram has no valid numeric data for '%s'.", x_field)
        return alt.Chart(pd.DataFrame({"count": []})).mark_bar()

    bin_edges = settings.get("bin_edges")
    counts = edges = None

    def _normalize_edges(edge_array):
        edge_array = np.asarray(edge_array, dtype=float)
        if edge_array.ndim != 1 or edge_array.size < 2 or not np.all(np.diff(edge_array) > 0):
            raise ValueError("bin_edges must be a strictly increasing list with at least two numbers.")
        return edge_array

    if bin_edges is not None:
        try:
            edges = _normalize_edges(bin_edges)
            counts, edges = np.histogram(x_values, bins=edges)
        except Exception as exc:
            logger.warning("Invalid bin_edges provided for histogram: %s", exc)
            edges = None

    if edges is None:
        bin_step = settings.get("bin_step")
        hist_range = None
        bin_min = settings.get("bin_min")
        bin_max = settings.get("bin_max")
        if bin_min is not None or bin_max is not None:
            min_val = float(bin_min) if bin_min is not None else float(np.min(x_values))
            max_val = float(bin_max) if bin_max is not None else float(np.max(x_values))
            if max_val <= min_val:
                max_val = min_val + 1
            hist_range = (min_val, max_val)

        if bin_step:
            try:
                step = float(bin_step)
                if step <= 0:
                    raise ValueError("bin_step must be positive.")
                start = float(hist_range[0]) if hist_range else float(np.min(x_values))
                stop = float(hist_range[1]) if hist_range else float(np.max(x_values))
                edges = np.arange(start, stop + step, step)
                if edges.size < 2:
                    edges = np.array([start, stop + step], dtype=float)
                counts, edges = np.histogram(x_values, bins=edges)
            except Exception as exc:
                logger.warning("Invalid bin_step provided for histogram: %s", exc)
                edges = None

        if edges is None:
            bins = settings.get("bins") or settings.get("max_bins") or settings.get("bin_count") or 40
            try:
                bins = int(bins)
            except Exception:
                bins = 40
            counts, edges = np.histogram(x_values, bins=bins, range=hist_range)

    hist_df = pd.DataFrame(
        {
            "bin_start": edges[:-1],
            "bin_end": edges[1:],
            "count": counts,
            "count_start": 0,
        }
    )

    tooltip = settings.get("tooltip")
    if not tooltip:
        tooltip = ["bin_start:Q", "bin_end:Q", "count:Q"]
    y_domain = settings.get("y_domain")
    y_scale_kwargs = {}
    if y_domain is not None:
        y_scale_kwargs["domain"] = y_domain
    else:
        y_scale_kwargs["domainMin"] = 0
    y_scale = alt.Scale(**y_scale_kwargs)
    fill_color = settings.get("fill_color")
    stroke_color = settings.get("stroke_color", "#0a2b63")
    stroke_width = settings.get("stroke_width", 1)

    bar_mark = dict(
        opacity=settings.get("opacity", 0.5),
        stroke=stroke_color,
        strokeWidth=stroke_width,
    )
    if fill_color:
        bar_mark["color"] = fill_color

    chart = (
        alt.Chart(hist_df)
        .mark_bar(**bar_mark)
        .encode(
            x=alt.X("bin_start:Q", title=settings.get("x_title", x_field)),
            x2="bin_end:Q",
            y=alt.Y(
                "count:Q",
                title=settings.get("y_title", "Count"),
                scale=y_scale,
            ),
            y2="count_start:Q",
            tooltip=tooltip,
        )
    )

    props = {
        "height": settings.get("height", 300),
        "width": settings.get("width", "container"),
    }
    if "title" in settings:
        props["title"] = settings["title"]

    return chart.properties(**props)


def create_word_cloud(data, settings):
    """Create a word cloud using the `wordcloud` library and return an HTML <img>."""
    if WordCloud is None:
        logger.error("wordcloud library is not installed; cannot render word cloud.")
        return '<div class="chart-error">wordcloud library is not installed</div>'

    df = pd.DataFrame(data).copy()

    # Determine text and weight fields with sensible fallbacks
    text_field = settings.get("text") or settings.get("word") or settings.get("x")
    weight_field = settings.get("weight") or settings.get("count") or settings.get("y")

    if not text_field and len(df.columns) > 0:
        text_field = df.columns[0]
    if not text_field or text_field not in df.columns:
        logger.error("Word cloud requires a text field in the data")
        return '<div class="chart-error">Word cloud requires a text/text column</div>'

    if not weight_field or weight_field not in df.columns:
        remaining_cols = [col for col in df.columns if col != text_field]
        if remaining_cols:
            weight_field = remaining_cols[0]
        else:
            weight_field = "_weight"
            df[weight_field] = 1

    df = df[[text_field, weight_field]].dropna(subset=[text_field])
    df[weight_field] = pd.to_numeric(df[weight_field], errors="coerce").fillna(1)
    df[text_field] = df[text_field].astype(str)

    max_words_raw = settings.get("max_words")
    max_words_val = None
    if max_words_raw is not None:
        try:
            max_words_val = int(max_words_raw)
        except Exception:
            max_words_val = None

    try:
        if max_words_val:
            df = df.sort_values(weight_field, ascending=False).head(max_words_val)
    except Exception:
        pass

    frequencies = {}
    for word, weight in zip(df[text_field], df[weight_field]):
        if not word:
            continue
        try:
            w = float(weight)
        except Exception:
            w = 1.0
        if w <= 0:
            continue
        frequencies[word] = frequencies.get(word, 0) + w

    if not frequencies:
        logger.warning("No data available for word cloud chart")
        return '<div class="chart-error">No data available for word cloud</div>'

    wc = WordCloud(
        width=int(settings.get("width", 700)),
        height=int(settings.get("height", 500)),
        background_color=settings.get("background_color", "white"),
        colormap=settings.get("color_scheme", "viridis"),
        max_words=max_words_val,
        prefer_horizontal=settings.get("prefer_horizontal", 0.9),
        stopwords=set(settings.get("stopwords", [])) if settings.get("stopwords") else None,
    ).generate_from_frequencies(frequencies)

    buffer = BytesIO()
    wc.to_image().save(buffer, format="PNG")
    img_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    chart_id = settings.get("chart_id", "word-cloud")
    title = settings.get("title", settings.get("chart_title", "Word Cloud"))
    img_style = settings.get("img_style", "width:100%;height:auto;display:block;")

    return (
        f'<div id="{chart_id}" class="word-cloud-chart" aria-label="{title}">'
        f'<img src="data:image/png;base64,{img_b64}" alt="{title}" style="{img_style}"/></div>'
    )


def apply_common_settings(chart, settings):
    """Apply common chart settings like axes, title, and encodings

    Dynamic behaviour controlled via settings:
      - x_type / y_type: 'Q' (quant), 'O' (ordinal), 'T' (time). Defaults to 'Q'.
      - x_sort / y_sort: list of categories to use as explicit sort/domain for ordinal axes.
      - x_domain / y_domain: explicit numeric domain for quantitative axes.
      - x_tick_integer / y_tick_integer: force integer ticks (tickMinStep=1 + integer format)
      - x_axis / y_axis: dict of axis options (labelAngle, tickCount, format, etc.)
      - x_axis_labels / y_axis_labels: optional list of labels to map numeric tick values to strings.
        Example: x_axis_labels=['Jan','Feb',...], with data values 1..12 will display month names.
    """
    encodings = {}

    def _build_axis(axis_settings: dict | None, integer_ticks: bool):
        ax_opts = {}
        if axis_settings:
            # copy known simple options through
            for k in ("labelAngle", "tickCount", "format", "title", "orient"):
                if k in axis_settings:
                    ax_opts[k] = axis_settings[k]
        if integer_ticks:
            ax_opts.setdefault("format", "d")
            ax_opts.setdefault("tickMinStep", 1)
        # always provide an Axis object
        return ax_opts

    def _build_scale(domain):
        if domain is None:
            return None
        return alt.Scale(domain=domain, nice=False)

    # helper to produce a Vega-Lite labelExpr for mapping numeric tick values to labels
    def _label_expr_for_labels(labels: list):
        # build a JSON array in JS and index by datum.value-1 (assumes 1-based values)
        # Limitations: this expects numeric 1..N values. If your data uses strings, consider
        # converting them to integers or using an ordinal axis with explicit sort.
        import json as _json
        js_array = _json.dumps(labels)
        # label expression: (labels)[datum.value - 1] || datum.value
        return f"({js_array})[datum.value - 1] || datum.value"

    # X-axis
    x_field = settings.get("x")
    if x_field:
        x_type = (settings.get("x_type") or "Q").upper()
        x_axis_settings = settings.get("x_axis") or {}
        x_integer = bool(settings.get("x_tick_integer", False))
        x_sort = settings.get("x_sort", None)
        x_domain = settings.get("x_domain", None)
        x_axis_labels = settings.get("x_axis_labels")

        axis_opts = _build_axis(x_axis_settings, x_integer)
        scale_obj = _build_scale(x_domain)

        # if axis labels provided and numeric mapping desired, set tickValues and labelExpr
        axis_kwargs = dict(axis_opts)
        if x_axis_labels:
            # tick values will be 1..len(labels)
            tick_vals = list(range(1, len(x_axis_labels) + 1))
            axis_kwargs["values"] = tick_vals
            axis_kwargs["labelExpr"] = _label_expr_for_labels(x_axis_labels)

        axis_obj = alt.Axis(**axis_kwargs) if axis_kwargs else alt.Axis()

        encodings["x"] = alt.X(
            f"{x_field}:{x_type}",
            title=settings.get("x_title", x_field),
            axis=axis_obj,
        )
        if scale_obj:
            encodings["x"].scale=scale_obj
        if x_sort:
            encodings["x"].sort=x_sort

    # Y-axis
    y_field = settings.get('y')
    if y_field:
        y_type = (settings.get("y_type") or "Q").upper()
        y_axis_settings = settings.get("y_axis") or {}
        y_integer = bool(settings.get("y_tick_integer", False))
        y_domain = settings.get("y_domain", None)
        y_axis_labels = settings.get("y_axis_labels")
        y_sort = settings.get("y_sort", None)
        axis_opts = _build_axis(y_axis_settings, y_integer)
        scale_obj = _build_scale(y_domain)

        axis_kwargs = dict(axis_opts)
        if y_axis_labels:
            tick_vals = list(range(1, len(y_axis_labels) + 1))
            axis_kwargs["Values"] = tick_vals
            axis_kwargs["labelExpr"] = _label_expr_for_labels(y_axis_labels)
        axis_obj = alt.Axis(**axis_kwargs) if axis_kwargs else alt.Axis()

        encodings["y"] = alt.Y(
            f"{y_field}:{y_type}",
            title=settings.get("y_title", y_field),
            axis=axis_obj,
            sort=settings.get("y_sort", None),
        )
        if scale_obj:
            encodings["y"].scale=scale_obj
        if y_sort:
            encodings["y"].sort=y_sort
               
    # Color encoding (optional)
    color_field = settings.get('color')
    if color_field:
        encodings['color'] = color_field

    # Tooltip (optional)
    tooltip_fields = settings.get('tooltips')
    if tooltip_fields:
        encodings['tooltip'] = tooltip_fields  # can be list of strings or alt.Tooltip instances

    # Apply encodings
    chart = chart.encode(**encodings)

    # Set properties
    props = {}
    if 'title' in settings:
        props['title'] = settings['title']
    props['height'] = settings.get('height', 300)
    props['width'] = settings.get('width', 'container')

    chart = chart.properties(**props)

    return chart
