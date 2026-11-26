import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

from utils.analysis_utils import sliding_window_correlation
from utils.data_utils import AREAS, load_data
from utils.explore_views import outlier_view, stl_spectrogram_view
from utils.sources import show_source_info
from utils.weather_utils import (
    APP_DAILY_BUDGET,
    MAX_LOCATIONS,
    WEEKLY_WEATHER,
    area_daily_weather,
    calls_used_today,
    ensure_weather,
    latest_era5_date,
    locations_for_area,
    read_weather,
    to_weekly,
    weather_year_selector,
)

# One page for the weather data (ERA5 from Open-Meteo), with a tab for each way of looking at it.
# The area comes from the global selector in the sidebar; years and settings are chosen in each tab.
st.set_page_config(page_title="Weather", layout="wide")
area = st.session_state["area"]
st.title(f"Weather in {AREAS[area]}")
show_source_info("weather")

# daily properties, with their names and units, for the selectors
VARIABLES = {
    "temperature_2m_mean": ("Mean temperature", "°C"),
    "temperature_2m_max": ("Maximum temperature", "°C"),
    "temperature_2m_min": ("Minimum temperature", "°C"),
    "precipitation_sum": ("Precipitation", "mm"),
    "rain_sum": ("Rain", "mm"),
    "snowfall_sum": ("Snowfall", "cm"),
    "wind_speed_10m_mean": ("Mean wind speed", "m/s"),
    "precipitation_hours": ("Hours with precipitation", "h"),
    "shortwave_radiation_sum": ("Solar radiation", "MJ/m²"),
    "et0_fao_evapotranspiration": ("Evapotranspiration", "mm"),
}


# one year of daily weather, averaged over the area's locations. Whatever is missing for this area
# and year is downloaded from Open-Meteo and saved in MongoDB first (see weather_utils.py).
def daily_weather_for_year():
    year = weather_year_selector()
    status = ensure_weather(area, year)
    weather = read_weather(area, year)
    if status["message"]:
        st.warning(status["message"])
    if weather.empty:
        return year, status, weather, None
    daily = weather.groupby("date").mean(numeric_only=True).drop(columns="point_id")
    return year, status, weather, daily


# several years of weekly weather (5 locations per area), stored in MongoDB after the first download
def weekly_weather_for_years(label, years):
    frames = []
    progress = st.empty()
    try:
        for year in range(years[0], years[1] + 1):
            progress.caption(f"Loading weather for {year}...")
            frames.append(area_daily_weather(area, year))
    except (requests.RequestException, RuntimeError) as error:
        st.warning(f"Could not get all the weather ({error}). Showing the years that loaded.")
    progress.empty()
    frames = [f for f in frames if not f.empty]
    return to_weekly(pd.concat(frames), label) if frames else None


def years_slider(key):
    last_year = latest_era5_date().year
    return st.select_slider("Years", options=list(range(2000, last_year + 1)), value=(last_year - 5, last_year),
                            key=key, help="Each new year costs about 130 weather calls the first time; after that it is stored.")


# ---- tab 1: the raw daily data for one year ----
def explore_tab():
    year, status, weather, daily = daily_weather_for_year()
    if daily is None:
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Precipitation in the year", f"{daily['precipitation_sum'].sum():,.0f} mm")
    c2.metric("Mean temperature", f"{daily['temperature_2m_mean'].mean():.1f} °C")
    c3.metric("Snowfall", f"{daily['snowfall_sum'].sum():,.0f} cm")

    plot_tab, table_tab = st.tabs(["Plot", "Table"])
    with plot_tab:
        # two charts on the same time axis instead of one chart with two y-axes
        fig = px.bar(daily.reset_index(), x="date", y="precipitation_sum",
                     labels={"date": "Date", "precipitation_sum": "Precipitation (mm per day)"},
                     title="Daily precipitation, average over the locations")
        fig.update_traces(marker_color="#2a78d6")
        st.plotly_chart(fig)
        fig = px.line(daily.reset_index(), x="date", y=["temperature_2m_min", "temperature_2m_mean", "temperature_2m_max"],
                      labels={"date": "Date", "value": "Temperature (°C)", "variable": ""},
                      title="Daily temperature, average over the locations",
                      color_discrete_sequence=["#9fc5f0", "#2a78d6", "#eb6834"])
        fig.for_each_trace(lambda t: t.update(name=t.name.replace("temperature_2m_", "").capitalize()))
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig)

    # every property for every day, with the properties the user picks
    with table_tab:
        columns = st.multiselect("Properties", [c for c in VARIABLES if c in daily.columns],
                                 default=["temperature_2m_mean", "precipitation_sum", "snowfall_sum"],
                                 format_func=lambda c: f"{VARIABLES[c][0]} ({VARIABLES[c][1]})", key="weather_table_columns")
        st.dataframe(
            daily[columns].round(1),
            column_config={"date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
                           **{c: f"{VARIABLES[c][0]} ({VARIABLES[c][1]})" for c in columns}},
            width="stretch",
        )

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
            "of the 1000 random locations the notebook sampled for the area."
        )
        st.map(points, latitude="lat", longitude="lon", size=3000)


# ---- tab 2: STL and spectrogram of weekly weather over several years ----
def stl_tab():
    c1, c2 = st.columns(2)
    with c1:
        label = st.selectbox("Weather property", list(WEEKLY_WEATHER), index=3, key="weather_stl_property")  # temperature
    with c2:
        years = years_slider("weather_stl_years")
    weekly = weekly_weather_for_years(label, years)
    if weekly is None:
        return
    st.caption(f"Weekly ERA5 data, average over 5 of the area's locations, {weekly.index.min():%d.%m.%Y} to "
               f"{weekly.index.max():%d.%m.%Y} ({len(weekly)} weeks).")
    name, unit = label.rsplit(" (", 1)
    stl_spectrogram_view(
        weekly, name, unit.rstrip(")"), period=52, samples_per_year=52, step="week", key="weather_stl",
        cycle_note="The seasons are at 1 cycle per year; weather has much more noise at higher frequencies than the reservoirs.",
    )


# ---- tab 3: outliers and anomalies in the daily data for one year ----
def outlier_tab():
    year, _, weather, daily = daily_weather_for_year()
    if daily is None:
        return
    st.caption(f"Daily ERA5 data from Open-Meteo, average over {weather['point_id'].nunique()} locations, "
               f"{daily.index.min():%d.%m.%Y} to {daily.index.max():%d.%m.%Y}.")
    # temperature is the default for the SPC outliers, precipitation for the LOF anomalies
    outlier_view(daily, VARIABLES, spc_default="temperature_2m_mean", lof_default="precipitation_sum",
                 step="day", period_text=str(year), key="weather")


# ---- tab 4: sliding window correlation between the weather and the reservoirs ----
RESERVOIR = {"Weekly change in fill ratio (pp)": "fill_ratio_change", "Fill ratio (%)": "fill_ratio"}
WEATHER_COLOUR, RESERVOIR_COLOUR, CORR_COLOUR = "#2a78d6", "#1baf7a", "#eb6834"


def correlation_tab():
    st.write(
        "Sliding window correlation between a weather property and the reservoirs, week by week. "
        "The lag moves the weather later in time, so a lag of 4 compares the reservoirs with the weather "
        "four weeks before. Where the correlation is strong and stable, the weather can help predict the reservoirs."
    )
    c1, c2, c3 = st.columns(3)
    weather_label = c1.selectbox("Weather property", list(WEEKLY_WEATHER), index=3, key="corr_weather")  # temperature
    # the weekly change is the default: rain and snowmelt change the filling in the same weeks
    reservoir_label = c2.selectbox("Magasinstatistikk", list(RESERVOIR), key="corr_reservoir")
    with c3:
        years = years_slider("corr_years")
    c4, c5 = st.columns(2)
    lag = c4.slider("Lag (weeks)", 0, 26, 0, key="corr_lag", help="How many weeks the weather comes before the reservoirs.")
    window = c5.slider("Window length (weeks)", 4, 104, 26, step=2, key="corr_window",
                       help="How many weeks each correlation is computed over.")

    # NVE's weeks end on Sundays, so the weather is summed or averaged Monday to Sunday (whole weeks only)
    weather = weekly_weather_for_years(weather_label, years)
    if weather is None:
        return
    df = load_data()
    reservoir = df[df["area"] == area].set_index("date")[RESERVOIR[reservoir_label]] * 100
    both = weather.rename("weather").to_frame().join(reservoir.rename("reservoir"), how="inner").dropna()
    if len(both) < window + lag:
        st.warning("Too few weeks for this window and lag. Choose more years or a shorter window.")
        return

    # the lag is applied on the joined weeks, so a lag of 1 is always the week before
    swc = sliding_window_correlation(both["weather"], both["reservoir"], window=window, lag=lag)
    overall = {k: both["weather"].shift(k).corr(both["reservoir"]) for k in range(0, 27)}
    best_lag = max(overall, key=lambda k: abs(overall[k]))

    m1, m2, m3 = st.columns(3)
    m1.metric(f"Correlation over all weeks, lag {lag}", f"{overall[lag]:+.2f}")
    m2.metric("Strongest lag over all weeks", f"{best_lag} weeks", f"correlation {overall[best_lag]:+.2f}", delta_color="off")
    m3.metric(f"Range of the {window}-week correlation", f"{swc.min():+.2f} to {swc.max():+.2f}")

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=(f"{weather_label}, moved {lag} weeks later", reservoir_label,
                                        f"Sliding window correlation ({window} weeks, lag {lag})"))
    fig.add_trace(go.Scatter(x=both.index, y=both["weather"].shift(lag), name=weather_label,
                             line=dict(color=WEATHER_COLOUR, width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=both.index, y=both["reservoir"], name=reservoir_label,
                             line=dict(color=RESERVOIR_COLOUR, width=1.5)), row=2, col=1)
    fig.add_trace(go.Scatter(x=swc.index, y=swc, name="Correlation", line=dict(color=CORR_COLOUR, width=2),
                             fill="tozeroy", fillcolor="rgba(235,104,52,0.15)"), row=3, col=1)
    fig.add_hline(y=0, line=dict(color="#8a8984", width=1), row=3, col=1)
    fig.update_yaxes(range=[-1, 1], title_text="r", row=3, col=1)
    fig.update_layout(height=720, hovermode="x unified", showlegend=False, margin=dict(t=40, b=30))
    fig.update_traces(hovertemplate="%{y:.2f}")
    st.plotly_chart(fig)

    # correlation for every lag over all the chosen weeks, to help pick the lag
    lags = pd.Series(overall)
    bar = go.Figure(go.Bar(x=lags.index, y=lags.values,
                           marker_color=[CORR_COLOUR if k == lag else "#b4c3d3" for k in lags.index],
                           hovertemplate="lag %{x} weeks: r = %{y:.2f}<extra></extra>"))
    bar.update_layout(height=280, title="Correlation over all weeks for each lag (the chosen lag in orange)",
                      xaxis_title="Lag (weeks)", yaxis=dict(title="r", range=[-1, 1]), margin=dict(t=50, b=40))
    st.plotly_chart(bar)
    st.caption(
        f"Weather: ERA5 from Open-Meteo, daily average over 5 of the area's sampled locations, summed or averaged "
        f"per week (Monday–Sunday). Reservoirs: NVE, weekly. {len(both)} weeks from {both.index.min():%d.%m.%Y} "
        f"to {both.index.max():%d.%m.%Y}."
    )


# on_change="rerun" makes the tabs lazy: only the open tab's code runs, so the multi-year weather for
# STL and correlation is only downloaded when one of those tabs is opened
tabs = st.tabs(["Explore the data", "STL and spectrogram", "Outliers and anomalies", "Weather and reservoirs"],
               key="weather_tab", on_change="rerun")
for tab, content in zip(tabs, [explore_tab, stl_tab, outlier_tab, correlation_tab]):
    if tab.open:
        with tab:
            content()
