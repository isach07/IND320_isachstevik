import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from utils.data_utils import AREAS, load_data
from utils.weather_utils import latest_era5_date, period_weather

st.set_page_config(page_title="Map", layout="wide")
st.title("Map of the areas")

# GeoJSON files made from the part 3 shapefiles in the part 4 notebook, one per area type
GEO_DIR = Path(__file__).parent.parent / "Data" / "geojson"
LAYERS = {
    "Norway (NO)": "norway",
    "Price areas (EL)": "price_areas",
    "Water areas (VASS)": "water_areas",
}
# weather properties: the ERA5 variable and how the daily values are combined over the period
WEATHER = {
    "Mean temperature (°C)": ("temperature_2m_mean", "mean"),
    "Precipitation (mm)": ("precipitation_sum", "sum"),
    "Snowfall (cm)": ("snowfall_sum", "sum"),
    "Mean wind speed (m/s)": ("wind_speed_10m_mean", "mean"),
    "Solar radiation (MJ/m²)": ("shortwave_radiation_sum", "sum"),
}
PERIODS = {"1 week": 1, "4 weeks": 4, "13 weeks": 13}
SELECTED_COLOUR = "#eb6834"  # orange: stands out against the blue fill and the grey outlines


@st.cache_data
def load_layer(name):
    return json.loads((GEO_DIR / f"{name}.geojson").read_text())


# the outline of every polygon in a layer as one line: lon/lat lists with None between the rings
def outline(geojson, areas=None):
    lons, lats = [], []
    for feature in geojson["features"]:
        if areas is not None and feature["properties"]["area"] not in areas:
            continue
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for polygon in polygons:
            for ring in polygon:
                lons += [p[0] for p in ring] + [None]
                lats += [p[1] for p in ring] + [None]
    return lons, lats


# ---- selectors ----
c1, c2, c3 = st.columns([1.2, 1, 1])
colour_by = c1.radio("Colour by", ["Price area", "Water area", "Weather property"], horizontal=True,
                     help="Price and water areas are coloured by how full their reservoirs are.")
if colour_by == "Weather property":
    weather_label = c2.selectbox("Weather property", list(WEATHER))
    weather_areas = c3.radio("Areas", ["Price areas (EL)", "Water areas (VASS)"], horizontal=True)
    coloured_layer = weather_areas
    period = c2.radio("Aggregated over", list(PERIODS), index=1, horizontal=True,
                      help="The weeks up to and including the chosen week.")
else:
    coloured_layer = "Price areas (EL)" if colour_by == "Price area" else "Water areas (VASS)"
outlines = c3.multiselect("Outlines", list(LAYERS), default=["Norway (NO)", coloured_layer],
                          help="Any of the three area types from Magasinstatistikk.")

df = load_data()
# the chosen time: a week (NVE gives one value per week, on Sundays). Weather is only available
# up to about a week ago, so the latest week for weather is earlier.
last_week = df["date"].max().date()
if colour_by == "Weather property":
    last_week = min(last_week, latest_era5_date() - timedelta(days=(latest_era5_date().weekday() + 1) % 7))
# The week is shared with the Forecast page (where it is the last week of the training data), so it
# is kept in session_state under its own key, like the weather year.
first_week = date(2000, 1, 2)
shared = min(max(st.session_state.get("week", last_week), first_week), last_week)
if "map_week" not in st.session_state or st.session_state.get("map_week_seen") != st.session_state.get("week"):
    st.session_state["map_week"] = shared  # first visit, or the week was changed on the Forecast page
chosen = st.slider("Week", min_value=first_week, max_value=last_week, key="map_week",
                   step=timedelta(weeks=1), format="DD.MM.YYYY",
                   help="The week ending on this Sunday. Shared with the Forecast page.")
st.session_state["week"] = st.session_state["map_week_seen"] = chosen
week_end = pd.Timestamp(chosen)

# ---- the value to colour each area by ----
layer_name = LAYERS[coloured_layer]
geojson = load_layer(layer_name)
areas = [f["properties"]["area"] for f in geojson["features"]]

if colour_by == "Weather property":
    variable, how = WEATHER[weather_label]
    start = (week_end - pd.Timedelta(weeks=PERIODS[period]) + pd.Timedelta(days=1)).date()
    values = {}
    try:
        with st.spinner("Downloading weather for the areas..."):
            for area in areas:
                daily = period_weather(area, start, week_end.date())[variable]
                values[area] = daily.mean() if how == "mean" else daily.sum()
    except (requests.RequestException, RuntimeError) as error:
        st.warning(f"Could not get the weather: {error}")
        st.stop()
    colour_title = weather_label
    # temperature has a natural middle at 0 °C, so it gets a diverging scale; the others go light to dark
    colourscale = "RdBu_r" if variable == "temperature_2m_mean" else "Blues"
    midpoint = 0 if variable == "temperature_2m_mean" else None
    zrange = (None, None)
    period_text = f"{start:%d.%m.%Y}–{week_end:%d.%m.%Y}, ERA5 average over 5 locations per area"
    value_format = ".1f"
else:
    latest = df[df["date"] <= week_end].sort_values("date").groupby("area").last()
    values = (latest["fill_ratio"] * 100).reindex(areas).to_dict()
    colour_title = "Fill ratio (%)"
    colourscale, midpoint, zrange = "Blues", None, (0, 100)  # fixed range, so weeks can be compared
    period_text = f"NVE, week {week_end:%V} {week_end:%G}"
    value_format = ".1f"

# ---- the map ----
fig = go.Figure(go.Choroplethmap(
    geojson=geojson,
    featureidkey="properties.area",
    locations=areas,
    z=[values[a] for a in areas],
    zmin=zrange[0], zmax=zrange[1], zmid=midpoint,
    colorscale=colourscale,
    marker=dict(opacity=0.55, line=dict(width=1, color="#2E3338")),  # transparent fill
    colorbar=dict(title=colour_title, thickness=12, len=0.6),
    customdata=[AREAS[a] for a in areas],
    hovertemplate=f"%{{customdata}}<br>{colour_title}: %{{z:{value_format}}}<extra></extra>",
))
# outlines of the other area types the user chose
for label in outlines:
    if label == coloured_layer:
        continue
    lons, lats = outline(load_layer(LAYERS[label]))
    fig.add_trace(go.Scattermap(lon=lons, lat=lats, mode="lines", line=dict(width=1.5, color="#5a6470"),
                                name=label, hoverinfo="skip"))
# the area chosen for the other pages gets a thick orange outline
selected = st.session_state["area"]
for label in [coloured_layer] + outlines:
    lons, lats = outline(load_layer(LAYERS[label]), areas=[selected])
    if lons:
        fig.add_trace(go.Scattermap(lon=lons, lat=lats, mode="lines", line=dict(width=4, color=SELECTED_COLOUR),
                                    name=AREAS[selected], hoverinfo="skip"))
        break
fig.update_layout(
    map=dict(style="carto-positron", center=dict(lat=65, lon=15), zoom=3.2),
    height=700, margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
    uirevision="map",  # keep the user's zoom and position when the page reruns
)


# a click on an area makes it the area of the whole app (the selector in the sidebar). This runs as a
# callback, before the page runs again, which is the only time a widget's value may be changed.
def select_area():
    points = st.session_state["map"].selection["points"]
    clicked = [p.get("location") for p in points if p.get("curve_number") == 0 and p.get("location")]
    if clicked:
        st.session_state["area"] = clicked[0]


st.plotly_chart(fig, key="map", on_select=select_area, selection_mode="points")
st.caption(
    f"{colour_title}: {period_text}. Click an area to choose it for the other pages "
    f"(now: {AREAS[selected]}, outlined in orange)."
)
