import pandas as pd
import plotly.express as px
import streamlit as st

from data_utils import AREAS
from weather_utils import (
    APP_DAILY_BUDGET,
    MAX_LOCATIONS,
    calls_used_today,
    ensure_weather,
    locations_for_area,
    read_weather,
    weather_year_selector,
)

st.set_page_config(page_title="Weather", layout="wide")

# the area comes from the global selector in the sidebar; the year is shared with the outlier page
area = st.session_state["area"]
st.title(f"Weather for {AREAS[area]}")

year = weather_year_selector()

# Download control is a hidden part of the app: whatever is missing for this area and year
# is downloaded from Open-Meteo and saved in MongoDB. The status below is the confirmation.
status = ensure_weather(area, year)
weather = read_weather(area, year)

if status["message"]:
    st.warning(status["message"])
if weather.empty:
    st.stop()

# average over the locations, one row per day
daily = weather.groupby("date").mean(numeric_only=True).drop(columns="point_id").reset_index()

c1, c2, c3 = st.columns(3)
c1.metric("Precipitation in the year", f"{daily['precipitation_sum'].sum():,.0f} mm")
c2.metric("Mean temperature", f"{daily['temperature_2m_mean'].mean():.1f} °C")
c3.metric("Snowfall", f"{daily['snowfall_sum'].sum():,.0f} cm")

# two charts on the same time axis instead of one chart with two y-axes
fig = px.bar(daily, x="date", y="precipitation_sum",
             labels={"date": "Date", "precipitation_sum": "Precipitation (mm per day)"},
             title="Daily precipitation, average over the locations")
fig.update_traces(marker_color="#2a78d6")
st.plotly_chart(fig)

fig = px.line(daily, x="date", y=["temperature_2m_min", "temperature_2m_mean", "temperature_2m_max"],
              labels={"date": "Date", "value": "Temperature (°C)", "variable": ""},
              title="Daily temperature, average over the locations",
              color_discrete_sequence=["#9fc5f0", "#2a78d6", "#eb6834"])
fig.for_each_trace(lambda t: t.update(name=t.name.replace("temperature_2m_", "").capitalize()))
fig.update_layout(hovermode="x unified")
st.plotly_chart(fig)

with st.expander("Download status and locations"):
    points = locations_for_area(area)
    st.write(
        f"**{weather['point_id'].nunique()} of {len(points)} locations** loaded for {year} "
        f"({status['stored']} were already stored, {status['downloaded']} downloaded now"
        f"{', ' + str(status['missing']) + ' missing' if status['missing'] else ''}). "
        f"Data up to {weather['date'].max():%d.%m.%Y}."
    )
    st.write(
        f"Weather downloads used today: {calls_used_today():,.0f} of the app's {APP_DAILY_BUDGET:,} calls. "
        f"One year for one location costs about 26 calls, so each area uses at most {MAX_LOCATIONS} "
        "of the 1000 random locations from the notebook."
    )
    st.map(points, latitude="lat", longitude="lon", size=3000)

st.caption("Source: Open-Meteo historical weather API, ERA5 reanalysis (about 25 km grid).")
