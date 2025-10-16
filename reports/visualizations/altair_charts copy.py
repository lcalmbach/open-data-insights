import pandas as pd
import altair as alt
import json
import logging
from reports.models import GraphType
from typing import List
import math

logger = logging.getLogger(__name__)

def generate_chart(data, settings, chart_id):
    """
    Generate an Altair chart based on data and settings
    
    Args:
        data (pd.DataFrame or list): Data for the chart, will be converted to DataFrame if needed
        settings (dict): Chart configuration settings
        chart_id (str): Unique identifier for the chart element
        
    Returns:
        str: HTML representation of the chart
    """
    try:
        # Process date columns
        #for col in data.columns:
        #    if data[col].dtype == 'object' and pd.to_datetime(data[col], errors='coerce').notna().all():
        #        data[col] = pd.to_datetime(data[col])
        
        # Determine chart type and call appropriate function.
        # Accept either a plain string in settings['type'] or a GraphType model/PK.
    
        
        chart_functions = {
            'line': create_line_chart,
            'bar': create_bar_chart,
            'bar_stacked': create_bar_stacked_chart,
            'area': create_area_chart,
            'point': create_point_chart,
            'scatter': create_point_chart,
            'pie': create_pie_chart,
            'heatmap': create_heatmap,
            'histogram': create_histogram,
        }
        
        chart_type = settings.get('type').value.lower()
        chart_func = chart_functions.get(chart_type, create_line_chart)
        
        # Create the chart
        chart = chart_func(data, settings)
        
        # Convert to HTML
        html = chart.to_html(
            embed_options={
                'actions': False,  # Hide download buttons
                'renderer': 'svg',  # SVG is better for print/static content
                'theme': settings.get('theme', 'default')
            }
        )
        
        # Replace default "vis" id with custom chart_id
        html = html.replace('id="vis"', f'id="{chart_id}"')
        html = html.replace('vegaEmbed("#vis"', f'vegaEmbed("#{chart_id}"')
        
        return html
    
    except Exception as e:
        logger.error(f"Error generating chart: {str(e)}")
        return f'<div id="{chart_id}" class="chart-error">Error generating chart: {str(e)}</div>'


def create_line_chart(data, settings):
    """Create a line chart with the given data and settings"""
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
    encodings = {}
    if x_field:
        if x_sort:
            encodings['x'] = alt.X(f"{x_field}:O", title=settings.get('x_title', x_field), sort=x_sort, axis=alt.Axis(labelAngle=0))
        else:
            encodings['x'] = alt.X(f"{x_field}:O", title=settings.get('x_title', x_field), axis=alt.Axis(labelAngle=0))
    # y: use provided y or count()
    if y_field:
        encodings['y'] = alt.Y(y_field, title=settings.get('y_title', y_field))
    else:
        encodings['y'] = alt.Y('count()', title=settings.get('y_title', 'count'))

    if color_field:
        encodings['color'] = alt.Color(color_field, scale=alt.Scale(scheme=settings.get('color_scheme', 'category10')))

    # Tooltip support
    tooltip = settings.get('tooltip')
    if tooltip:
        encodings['tooltip'] = tooltip
    else:
        # include sensible defaults
        tt = []
        if x_field:
            tt.append(x_field)
        if y_field:
            tt.append(y_field)
        if color_field:
            tt.append(color_field)
        if tt:
            encodings['tooltip'] = tt

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
    
    # Create stacked encoding
    encodings = {
        'x': alt.X(
            x_field, 
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
        encodings['tooltip'] = [x_field, y_field, color_field]
    
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


def apply_common_settings(chart, settings):
    """Apply common chart settings like axes, title, and encodings

    Dynamic behaviour controlled via settings:
      - x_type / y_type: 'Q' (quant), 'O' (ordinal), 'T' (time). Defaults to 'Q'.
      - x_sort / y_sort: list of categories to use as explicit sort/domain for ordinal axes.
      - x_domain / y_domain: explicit numeric domain for quantitative axes.
      - x_tick_integer / y_tick_integer: force integer ticks (tickMinStep=1 + integer format)
      - x_axis / y_axis: dict of axis options (labelAngle, tickCount, format, etc.)
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
        return alt.Axis(**ax_opts) if ax_opts else alt.Axis()

    def _build_scale(domain):
        if domain is None:
            return None
        return alt.Scale(domain=domain, nice=False)

    # X-axis
    x_field = settings.get("x")
    if x_field:
        x_type = (settings.get("x_type") or "Q").upper()
        x_axis_settings = settings.get("x_axis") or {}
        x_integer = bool(settings.get("x_tick_integer", False))
        x_sort = settings.get("x_sort", None)
        x_domain = settings.get("x_domain", None)

        axis_obj = _build_axis(x_axis_settings, x_integer)
        scale_obj = _build_scale(x_domain)

        if x_type == "O":
            # ordinal axis; allow explicit sort list
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
                #scale=scale_obj if scale_obj is not None else None,
            )
        else:  # quantitative
            encodings["x"] = alt.X(
                f"{x_field}:Q",
                title=settings.get("x_title", x_field),
                axis=axis_obj,
                #scale=scale_obj if scale_obj is not None else None,
            )

    # Y-axis
    y_field = settings.get("y")
    if y_field:
        y_type = (settings.get("y_type") or "Q").upper()
        y_axis_settings = settings.get("y_axis") or {}
        y_integer = bool(settings.get("y_tick_integer", False))
        y_domain = settings.get("y_domain", None)

        axis_obj = _build_axis(y_axis_settings, y_integer)
        scale_obj = _build_scale(y_domain)

        if y_type == "O":
            encodings["y"] = alt.Y(
                f"{y_field}:O",
                title=settings.get("y_title", y_field),
                axis=axis_obj,
                sort=settings.get("y_sort", None),
            )
        elif y_type == "T":
            encodings["y"] = alt.Y(
                f"{y_field}:T",
                title=settings.get("y_title", y_field),
                axis=axis_obj,
                #scale=scale_obj if scale_obj is not None else None,
            )
        elif y_type == "N":
            encodings["y"] = alt.Y(
                f"{y_field}:N",
                title=settings.get("y_title", y_field),
                axis=axis_obj,
                #scale=scale_obj if scale_obj is not None else None,
            )
        else:
            encodings["y"] = alt.Y(
                f"{y_field}:Q",
                title=settings.get("y_title", y_field),
                axis=axis_obj,
                #scale=scale_obj if scale_obj is not None else None,
            )

    # Color encoding (optional)
    color_field = settings.get("color")
    if color_field:
        encodings["color"] = color_field

    # Tooltip (optional)
    tooltip_fields = settings.get("tooltips")
    if tooltip_fields:
        encodings["tooltip"] = tooltip_fields  # can be list of strings or alt.Tooltip instances

    # Apply encodings when present
    if encodings:
        chart = chart.encode(**encodings)

    # Set properties
    props = {}
    if "title" in settings:
        props["title"] = settings["title"]
    props["height"] = settings.get("height", 300)
    props["width"] = settings.get("width", "container")

    chart = chart.properties(**props)

    return chart
