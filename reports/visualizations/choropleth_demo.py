from __future__ import annotations

from reports.visualizations.plotting import create_chloropleth


LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"


def build_demo_page() -> str:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "west", "name": "West"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-123.5, 38.0],
                            [-121.0, 38.0],
                            [-121.0, 36.0],
                            [-123.5, 36.0],
                            [-123.5, 38.0],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"id": "south", "name": "South"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-121.0, 36.0],
                            [-118.0, 36.0],
                            [-118.0, 33.0],
                            [-121.0, 33.0],
                            [-121.0, 36.0],
                        ]
                    ],
                },
            },
        ],
    }

    data = [
        {"id": "west", "value": 12, "label": "Region West"},
        {"id": "south", "value": 42, "label": "Region South"},
    ]

    fragment = create_chloropleth(
        data,
        {
            "chart_id": "demo_choropleth",
            "geojson": geojson,
            "data_key": "id",
            "geo_key": "id",
            "value": "value",
            "tooltip": ["label", {"label": "Value", "field": "value"}],
            "legend_title": "Demo value",
            "height": 380,
        },
    )

    head_assets = "\n".join(
        [
            f'<link rel="stylesheet" href="{LEAFLET_CSS}" crossorigin="">',
            f'<script src="{LEAFLET_JS}" crossorigin=""></script>',
        ]
    )

    return (
        "<!doctype html>\n"
        "<html>\n"
        "<head>\n"
        '  <meta charset="utf-8">\n'
        "  <title>Leaflet Choropleth Demo</title>\n"
        f"{head_assets}\n"
        "</head>\n"
        "<body>\n"
        f"{fragment}\n"
        "</body>\n"
        "</html>\n"
    )


if __name__ == "__main__":
    print(build_demo_page())

