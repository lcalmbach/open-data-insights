import pandas as pd
import altair as alt
import json
import logging

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
        # Convert to DataFrame if needed
        if not isinstance(data, pd.DataFrame):
            data = pd.DataFrame(data)
        
        # Process date columns
        for col in data.columns:
            if data[col].dtype == 'object' and pd.to_datetime(data[col], errors='coerce').notna().all():
                data[col] = pd.to_datetime(data[col])
        
        # Determine chart type and call appropriate function
        chart_type = settings.get('type', 'line')
        
        chart_functions = {
            'line': create_line_chart,
            'bar': create_bar_chart,
            'bar_stacked': create_bar_stacked_chart,  # Add this line
            'area': create_area_chart,
            'point': create_point_chart,
            'scatter': create_point_chart,  # Scatter is an alias for point
            'pie': create_pie_chart,
            'heatmap': create_heatmap,
            'histogram': create_histogram
        }
        
        # Get the chart creation function, default to line chart
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
    # Create base chart
    chart = alt.Chart(data).mark_bar(
        cornerRadiusTopLeft=settings.get('corner_radius', 0),
        cornerRadiusTopRight=settings.get('corner_radius', 0)
    )
    
    # Apply encodings and properties
    chart = apply_common_settings(chart, settings)
    
    # Bar-specific settings
    if settings.get('horizontal', False):
        # Swap x and y for horizontal bars
        encodings = chart.encoding.copy()
        if hasattr(encodings, 'x') and hasattr(encodings, 'y'):
            temp_x = encodings.x
            encodings.x = encodings.y
            encodings.y = temp_x
            chart = chart.encode(**encodings)
    
    return chart


def create_bar_stacked_chart(data, settings):
    """Create a stacked bar chart with the given data and settings"""
    # Create base chart
    chart = alt.Chart(data).mark_bar(
        cornerRadiusTopLeft=settings.get('corner_radius', 0),
        cornerRadiusTopRight=settings.get('corner_radius', 0)
    )
    
    # Get fields
    x_field = settings.get('x')
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
    color_field = settings.get('color', settings.get('z'))
    
    if not x_field or not y_field or not color_field:
        logger.error("Heatmap requires 'x', 'y', and 'color' (or 'z') fields")
        return alt.Chart(data).mark_point()  # Return empty chart
    
    # Encode x, y and color
    chart = chart.encode(
        x=x_field,
        y=y_field,
        color=alt.Color(
            color_field,
            scale=alt.Scale(
                scheme=settings.get('color_scheme', 'viridis'),
                domain=settings.get('color_domain', None)
            )
        )
    )
    
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
    """Apply common chart settings like axes, title, and encodings"""
    # Configure encodings
    encodings = {}
    
    # X-axis
    x_field = settings.get('x')
    if x_field:
        encodings['x'] = alt.X(
            x_field, 
            title=settings.get('x_title', x_field),
            scale=alt.Scale(zero=settings.get('x_zero', False))
        )
        
    # Y-axis
    y_field = settings.get('y')
    if y_field:
        encodings['y'] = alt.Y(
            y_field, 
            title=settings.get('y_title', y_field),
            scale=alt.Scale(zero=settings.get('y_zero', True))
        )
    
    # Color encoding (optional)
    color_field = settings.get('color')
    if color_field:
        encodings['color'] = color_field
    
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