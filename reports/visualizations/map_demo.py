from __future__ import annotations

from reports.visualizations.plotting import create_map_markers


LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
MARKERCLUSTER_CSS = "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"
MARKERCLUSTER_DEFAULT_CSS = (
    "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"
)
MARKERCLUSTER_JS = "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"


def build_demo_page() -> str:
    data_one = [
        {"name": "Point A", "lat": 40.7128, "lon": -74.0060},
        {"name": "Point B", "lat": 40.7306, "lon": -73.9352},
    ]
    data_two = [
        {"name": "Point C", "lat": 37.7749, "lon": -122.4194},
        {"name": "Point D", "lat": 37.8044, "lon": -122.2711},
        {"name": "Point E", "lat": 37.6879, "lon": -122.4702},
    ]

    map_one = create_map_markers(
        data_one,
        {
            "latitude": "lat",
            "longitude": "lon",
            "chart_id": "demo_map_one",
            "marker_style": "circle",
            "circle_color": "#1d6fa5",
            "tooltip": "name",
            "height": 320,
        },
    )
    map_two = create_map_markers(
        data_two,
        {
            "latitude": "lat",
            "longitude": "lon",
            "chart_id": "demo_map_two",
            "marker_style": "marker",
            "cluster": True,
            "tooltip": "name",
            "height": 320,
        },
    )

    fragments = [map_one, map_two]
    needs_leaflet = any('data-leaflet-map="1"' in frag for frag in fragments)
    needs_markercluster = any('data-markercluster="1"' in frag for frag in fragments)

    head_assets = []
    if needs_leaflet:
        head_assets.append(f'<link rel="stylesheet" href="{LEAFLET_CSS}" crossorigin="">')
        head_assets.append(f'<script src="{LEAFLET_JS}" crossorigin=""></script>')
    if needs_markercluster:
        head_assets.append(
            f'<link rel="stylesheet" href="{MARKERCLUSTER_CSS}" crossorigin="">'
        )
        head_assets.append(
            f'<link rel="stylesheet" href="{MARKERCLUSTER_DEFAULT_CSS}" crossorigin="">'
        )
        head_assets.append(
            f'<script src="{MARKERCLUSTER_JS}" crossorigin=""></script>'
        )

    body = "\n".join(fragments)
    head = "\n".join(head_assets)

    return (
        "<!doctype html>\n"
        "<html>\n"
        "<head>\n"
        '  <meta charset="utf-8">\n'
        "  <title>Leaflet Map Demo</title>\n"
        f"{head}\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


if __name__ == "__main__":
    print(build_demo_page())
