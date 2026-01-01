import base64
import logging
from io import BytesIO
from typing import List

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
            "area": create_area_chart,
            "point": create_point_chart,
            "scatter": create_point_chart,
            "pie": create_pie_chart,
            "heatmap": create_heatmap,
            "histogram": create_histogram,
            "wordcloud": create_word_cloud
        }
        chart_type = settings.get('type').value.lower()
        chart_func = chart_functions.get(chart_type, create_line_chart)
        chart = chart_func(data, settings)

        if chart_type not in ("wordcloud",):
            html = chart.to_html(
                embed_options={
                    "actions": False,  # Hide download buttons
                    "renderer": "svg",  # SVG is better for print/static content
                    "theme": settings.get("theme", "default"),
                }
            )

            html = html.replace('id="vis"', f'id="{chart_id}"')
            html = html.replace('vegaEmbed("#vis"', f'vegaEmbed("#{chart_id}"')
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
    
    # Create base chart
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


def create_histogram(data, settings):
    """Create a histogram with the given data and settings"""
    # Get the field to bin
    x_field = settings.get('x')
    if not x_field:
        logger.error("Histogram requires 'x' field to bin")
        return alt.Chart(data).mark_point()  # Return empty chart
    
    # Create histogram chart
    bin_params = {}
    if 'bin_step' in settings:
        bin_params['step'] = settings['bin_step']
    if 'max_bins' in settings:
        bin_params['maxbins'] = settings['max_bins']
    
    chart = alt.Chart(data).mark_bar().encode(
        x=alt.X(f"{x_field}:Q", bin=alt.Bin(**bin_params)),
        y='count()'
    )
    
    # Apply color if specified
    color_field = settings.get('color')
    if color_field:
        chart = chart.encode(color=color_field)
    
    # Set properties
    props = {}
    if 'title' in settings:
        props['title'] = settings['title']
    props['height'] = settings.get('height', 300)
    props['width'] = settings.get('width', 'container')
    
    chart = chart.properties(**props)
    
    return chart


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

        if x_type == "O":
            encodings["x"] = alt.X(
                f"{x_field}:O",
                title=settings.get("x_title", x_field),
                sort=x_sort,
                axis=axis_obj,
            )
        elif x_type == "T":
            encodings["x"] = alt.X(
                f"{x_field}:T",
                title=settings.get("x_title", x_field),
                axis=axis_obj,
                # scale=scale_obj if scale_obj is not None else None,
            )
        else:  # quantitative
            encodings["x"] = alt.X(
                f"{x_field}:Q",
                title=settings.get("x_title", x_field),
                axis=axis_obj,
                #scale=scale_obj if scale_obj is not None else None,
            )

    # Y-axis
    y_field = settings.get('y')
    if y_field:
        y_type = (settings.get("y_type") or "Q").upper()
        y_axis_settings = settings.get("y_axis") or {}
        y_integer = bool(settings.get("y_tick_integer", False))
        y_domain = settings.get("y_domain", None)
        y_axis_labels = settings.get("y_axis_labels")

        axis_opts = _build_axis(y_axis_settings, y_integer)
        scale_obj = _build_scale(y_domain)

        axis_kwargs = dict(axis_opts)
        if y_axis_labels:
            tick_vals = list(range(1, len(y_axis_labels) + 1))
            axis_kwargs["Values"] = tick_vals
            axis_kwargs["labelExpr"] = _label_expr_for_labels(y_axis_labels)
        axis_obj = alt.Axis(**axis_kwargs) if axis_kwargs else alt.Axis()

        if y_type == "O":
            encodings["y"] = alt.Y(
                f"{y_field}:O",
                title=settings.get("y_title", y_field),
                axis=axis_obj,
                sort=settings.get("y_sort", None),
            )
        else:
            if scale_obj:
                encodings['y'] = alt.Y(
                    f"{y_field}:Q",
                    title=settings.get("y_title", y_field),
                    axis=axis_obj,
                    scale=scale_obj if scale_obj is not None else None,
                    sort=settings.get("y_sort", None),
                )
            else:
                encodings['y'] = alt.Y(
                    f"{y_field}:Q",
                    title=settings.get("y_title", y_field),
                    axis=axis_obj,
                    sort=settings.get("y_sort", None),
                )
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
