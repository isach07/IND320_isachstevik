from pathlib import Path

import streamlit as st
import pandas as pd
import requests
from utils.data_utils import AREAS, load_data
from utils.mongo_utils import load_crossborder
from utils.weather_utils import recent_weather

st.set_page_config(page_title="Home", layout="wide")

# the page content below is what streamlit shows when opening home.
# HTML is used for the title because st.title cannot underline a single word;
# the blue line under "better" uses the same blue as the theme (.streamlit/config.toml).
st.markdown(
    '<h1>Knowing data – unlocks '
    '<span style="border-bottom: 0.12em solid #2B6CB0; padding-bottom: 0.02em;">better</span> '
    'decisions</h1>',
    unsafe_allow_html=True,
)

# animated landscape: snow melts into the reservoir and power lines carry the energy to a town.
# It is a plain SVG with CSS animations (made once with a small script), so it needs no JavaScript.
st.image(str(Path(__file__).parent / "assets" / "landscape.svg"), width="stretch")

df = load_data()

st.write(
    "Norway's power comes almost entirely from water stored in its hydropower reservoirs. Every year "
    "they follow the same cycle: they drain through the winter, when demand is high and the rivers are "
    "frozen, and refill when the snow melts in late spring and summer."
)
st.write(
    "That cycle is under pressure. A changing climate brings less snow in the mountains and smaller "
    "glaciers, so the reservoirs can struggle to fill up again. At the same time, more of society is "
    "moving over to clean electricity, and Norway exports more power to Europe, which has needed "
    "energy even more since the war in Ukraine. More demand from less predictable water makes a good "
    "overview of the changes important."
)
st.write(
    "This app is a tool for investigating that: how full the reservoirs are (weekly statistics from NVE "
    f"since {df['date'].min():%Y}), the weather that fills them (ERA5 from Open-Meteo), and the power "
    "that flows to and from Europe (ENTSO-E)."
)

# A big button in the middle of the page that leads to the Forecast page. The CSS targets the
# button through its key (Streamlit gives the element the class "st-key-lets_go").
st.markdown(
    """
    <style>
      .st-key-lets_go button { font-size: 1.35rem; font-weight: 600; padding: 0.9rem 2.8rem; min-height: 3.6rem; }
      .st-key-lets_go button p { font-size: 1.35rem; }
    </style>
    <p style="text-align: center; font-size: 1.25rem; margin: 1.2rem 0 0.4rem;">
      Start by exploring the future of the water levels
    </p>
    """,
    unsafe_allow_html=True,
)
_, middle, _ = st.columns([1, 1, 1])
# the button sets a flag, so the Forecast page knows to start with the waterfall animation
if middle.button("Let's go", key="lets_go", type="primary", icon=":material/water:", width="stretch",
                 help="See the forecast for the coming months"):
    st.session_state["waterfall"] = True
    st.switch_page("app_pages/9_Forecast.py")

# ---- the last 30 days for the area chosen in the sidebar ----
area = st.session_state["area"]
st.subheader(f"Last 30 days in {AREAS[area]}")

# reservoirs: the weeks in the last 30 days, and the change since the week before them
fill = df[df["area"] == area].set_index("date")["fill_ratio"] * 100
recent_fill = fill[fill.index > fill.index.max() - pd.Timedelta(days=30)]
fill_change = recent_fill.iloc[-1] - fill[fill.index < recent_fill.index.min()].iloc[-1]

# weather: daily average over a few of the area's sampled locations
try:
    weather = recent_weather(area)
except requests.RequestException:
    weather = None

# cross-border flows: the price area's own connections; for Norway and the VASS areas, all of them
flows = load_crossborder()
if not flows.empty:
    if area.startswith("EL"):
        flows = flows[flows["connection"].str.startswith(f"NO_{area[-1]}-")]
    flows = flows[flows["date"] > flows["date"].max() - pd.Timedelta(days=30)]
    daily_flow = flows.pivot_table(index="date", columns="direction", values="flow_mwh", aggfunc="sum") / 1000  # GWh

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(
    f"Fill ratio, week {fill.index.max():%V}",
    f"{recent_fill.iloc[-1]:.1f} %",
    f"{fill_change:+.1f} pp in 30 days",
    chart_data=recent_fill.round(1), border=True,
)
if weather is not None:
    c2.metric("Mean temperature", f"{weather['temperature_2m_mean'].mean():.1f} °C",
              chart_data=weather["temperature_2m_mean"].round(1), border=True)
    c3.metric("Precipitation", f"{weather['precipitation_sum'].sum():.0f} mm",
              f"of which {weather['snowfall_sum'].sum():.0f} cm snow", delta_color="off", delta_arrow="off",
              chart_data=weather["precipitation_sum"].round(1), chart_type="bar", border=True)
else:
    c2.metric("Mean temperature", "–", border=True)
    c3.metric("Precipitation", "–", border=True)
if not flows.empty:
    for col, direction, label in [(c4, "into Norway", "Power in (import)"), (c5, "out of Norway", "Power out (export)")]:
        col.metric(label, f"{daily_flow[direction].sum() / 1000:.2f} TWh",
                   chart_data=daily_flow[direction].round(1), chart_type="area", border=True)
else:
    c4.metric("Power in (import)", "–", border=True)
    c5.metric("Power out (export)", "–", border=True)

notes = [f"Reservoirs: NVE, weekly, up to {fill.index.max():%d.%m.%Y}."]
notes.append("Weather: Open-Meteo, daily average over 5 of the area's sampled locations."
             if weather is not None else "Weather: Open-Meteo did not answer, try again later.")
if flows.empty:
    notes.append("Power: this area has no connections abroad." if area.startswith("EL") else "Power: no cross-border data in MongoDB yet.")
else:
    scope = "this area's connections abroad" if area.startswith("EL") else "all connections abroad"
    notes.append(f"Power: ENTSO-E, {scope}, {flows['date'].min():%d.%m}–{flows['date'].max():%d.%m.%Y} (the latest stored data).")
st.caption(" ".join(notes))

st.subheader("What you can explore")
st.markdown(
    "- **Map:** the price and water areas, coloured by fill ratio or weather for any week.\n"
    "- **Forecast:** the fill ratio for the coming months, with confidence intervals.\n"
    "- **Explore the data:** one page per data source (reservoirs, weather and cross-border flows), "
    "each with tabs for the raw data, the seasonal pattern (STL and spectrogram) and unusual values "
    "(outliers and anomalies). The weather page also shows how the weather relates to the reservoirs.\n\n"
    "Choose the area in the sidebar; it is used on every page."
)
