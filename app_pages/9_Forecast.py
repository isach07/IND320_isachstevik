import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from utils import forecast_utils as fu
from utils.data_utils import AREAS, load_data
from utils.weather_utils import WEEKLY_WEATHER, area_daily_weather, latest_era5_date, missing_area_years, to_weekly

st.set_page_config(page_title="Forecast", layout="wide")

# coming from the "Let's go" button on the home page: a waterfall covers the page for a moment
# (only once; the flag is removed, so changing a setting does not show it again)
if st.session_state.pop("waterfall", False):
    st.markdown((Path(__file__).parent / "assets" / "waterfall.html").read_text(), unsafe_allow_html=True)

area = st.session_state["area"]
st.title(f"Forecast of the reservoir filling in {AREAS[area]}")
st.write(
    "SARIMAX from River, with a seasonal period of 52 weeks, learns from the chosen training weeks and "
    "forecasts the coming weeks dynamically: each week ahead builds on the model's own forecast for the "
    "week before. The default settings are the best ones from the tests in the part 4 notebook."
)

EXCHANGE_RATE = "EUR/NOK exchange rate"
HISTORY, ACTUAL, FORECAST = "#2a78d6", "#8a8984", "#eb6834"
defaults = fu.DEFAULTS["model_params"]


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Downloading exchange rates from Norges Bank...")
def exchange_rates():
    return fu.load_exchange_rates()


# ---- model parameters ----
st.subheader("Model")
c = st.columns(7)
p = c[0].number_input("p (AR)", 0, 4, defaults["p"], help="How many earlier weeks the model uses.")
d = c[1].number_input("d (differencing)", 0, 2, defaults["d"], help="1: model the change from last week.")
q = c[2].number_input("q (MA)", 0, 3, defaults["q"], help="How many earlier forecast errors the model uses.")
sp = c[3].number_input("P (seasonal AR)", 0, 2, defaults["sp"], help="The same weeks in earlier years.")
sd = c[4].number_input("D (seasonal differencing)", 0, 1, defaults["sd"],
                       help="1: model the change from the same week last year. Needed for good forecasts.")
sq = c[5].number_input("Q (seasonal MA)", 0, 2, defaults["sq"])
learning_rate = c[6].select_slider("Learning rate", [0.001, 0.003, 0.01, 0.03], defaults["learning_rate"],
                                   help="For the online linear regression inside River's SNARIMAX.")
params = dict(p=p, d=d, q=q, sp=sp, sd=sd, sq=sq, learning_rate=learning_rate)

# ---- exogenous variables ----
c1, c2 = st.columns([2, 1])
exog_labels = c1.multiselect("Exogenous variables", list(WEEKLY_WEATHER) + [EXCHANGE_RATE],
                             help="Weather for the area (ERA5, 5 locations) and the exchange rate from Norges Bank. "
                                  "None by default: in the notebook tests they made the forecasts worse.")
future_mode = c2.radio("Future values of the exogenous variables", ["normal", "observed"], disabled=not exog_labels,
                       format_func={"normal": "Normal for the week (real forecast)",
                                    "observed": "What really happened (past only)"}.get,
                       help="The future weather is not known when forecasting. 'What really happened' shows how "
                            "good the forecast could be with perfect weather knowledge.")

# ---- confidence intervals ----
QUANTILE, PAST_ERRORS = "Quantile loss", "Past forecast errors"
interval_method = st.radio(
    "Confidence intervals", [QUANTILE, PAST_ERRORS], horizontal=True,
    help="Quantile loss: extra SARIMAX models trained with optim.losses.Quantile learn the lower and upper "
         "bound one week ahead, and the interval is widened for later weeks. Past forecast errors: the model "
         "forecasts from 26 earlier weeks in the training data, and the bands hold 80 % and 90 % of its errors.")
LEVELS = (0.8, 0.9)

# ---- training timeframe and horizon ----
df = load_data()
# every Sunday; the odd missing week is filled in with a straight line
filling = (df[df["area"] == area].set_index("date")["fill_ratio"].sort_index().asfreq("W-SUN") * 100).interpolate(limit_area="inside")
first, last = filling.index.min().date(), filling.index.max().date()
# The last training week is shared with the Map page's week. The slider has a fixed key, and its value
# is only set here when the shared week was changed on the Map page (or on the first visit).
shared_end = min(max(st.session_state.get("week", last), first + timedelta(weeks=156)), last)
if "training" not in st.session_state or st.session_state.get("forecast_week") != st.session_state.get("week"):
    st.session_state["training"] = (max(first, shared_end - timedelta(weeks=52 * fu.DEFAULTS["history_years"])),
                                    shared_end)
c1, c2 = st.columns([3, 1])
start, end = c1.slider("Training data", min_value=first, max_value=last, key="training",
                       step=timedelta(weeks=1), format="DD.MM.YYYY",
                       help="The forecast starts after the last training week. That week is shared with the Map page.")
st.session_state["week"] = st.session_state["forecast_week"] = end
horizon = c2.slider("Forecast horizon (weeks)", 1, 52, fu.DEFAULTS["horizon_weeks"])
start, end = pd.Timestamp(start), pd.Timestamp(end)
if end - start < pd.Timedelta(weeks=156):
    st.warning("Choose at least three years of training data: the seasonal part needs earlier years to learn from.")
    st.stop()
future_dates = pd.date_range(end + pd.Timedelta(weeks=1), periods=horizon, freq="W-SUN")

# ---- the data table: filling and the chosen exogenous variables ----
data = filling.rename("filling").to_frame()
weather_labels = [label for label in exog_labels if label in WEEKLY_WEATHER]
if weather_labels:
    # the weather is needed for the training weeks, and for the forecast weeks if they are used
    last_needed = min(future_dates[-1] if future_mode == "observed" else end, pd.Timestamp(latest_era5_date()))
    years = list(range(start.year, last_needed.year + 1))
    missing = missing_area_years(area, years)
    if missing:
        st.info(f"The weather for {len(missing)} of these years is not stored yet. Downloading it costs about "
                f"{130 * len(missing):,} of the app's 5,000 Open-Meteo calls per day, and takes about "
                f"{1 + len(missing) // 4} minute(s).")
        if not st.button("Download the weather"):
            st.stop()
    try:
        with st.spinner("Loading the weather..."):
            daily = pd.concat(area_daily_weather(area, y) for y in years)
    except (requests.RequestException, RuntimeError) as error:
        st.warning(f"Could not get the weather: {error}")
        st.stop()
    for label in weather_labels:
        data = data.join(to_weekly(daily, label))
if EXCHANGE_RATE in exog_labels:
    data = data.join(exchange_rates().rename(EXCHANGE_RATE))
if data.loc[start:end, exog_labels].isna().all().any():
    st.warning("Some exogenous variables have no data in the training period (the exchange rate starts in 1999).")
    st.stop()


# ---- forecast and intervals ----
@st.cache_data(show_spinner="Forecasting...")
def run(data, start, end, horizon, exog, params, future_mode, interval_method):
    t0 = time.perf_counter()
    forecast = fu.forecast_window(data, start, end, horizon, exog, dict(params), future_mode)
    seconds = time.perf_counter() - t0
    if interval_method == QUANTILE:
        bands, n = fu.quantile_bands(data, start, end, horizon, exog, dict(params), LEVELS, future_mode), None
    else:
        bands, n = fu.error_bands(data, start, end, horizon, exog, dict(params), levels=LEVELS)
    return forecast, bands, n, seconds


try:
    forecast, bands, n_past, seconds = run(data, start, end, horizon, tuple(exog_labels),
                                           tuple(params.items()), future_mode, interval_method)
except Exception as error:  # River can fail on unusual settings, e.g. too little history for the orders
    st.error(f"The model could not be fitted with these settings: {error}")
    st.stop()

actual = filling.reindex(future_dates)
m = st.columns(4)
m[0].metric(f"Filling, week {end:%V} {end:%G}", f"{filling.loc[end]:.1f} %")
m[1].metric(f"Forecast, week {future_dates[-1]:%V} {future_dates[-1]:%G}", f"{forecast.iloc[-1]:.1f} %",
            f"{forecast.iloc[-1] - filling.loc[end]:+.1f} pp", delta_color="off")
if actual.notna().any():
    m[2].metric("Mean error of this forecast", f"{(forecast - actual).abs().mean():.1f} pp",
                f"{actual.notna().sum()} weeks with known filling", delta_color="off")
if 0.8 in bands:
    m[3].metric("80 % interval in the last week", f"{bands[0.8][1][-1] - bands[0.8][0][-1]:.1f} pp wide")

# ---- animated plot: the forecast grows one week at a time ----
# a year of history (more for long horizons), so the forecast is not squeezed at the right
shown = filling.loc[max(start, end - pd.Timedelta(weeks=max(52, 3 * horizon))):end]
# every forecast line starts at the last observed week, so the line is connected
x_fc = [end] + list(future_dates)
y_fc = np.r_[filling.loc[end], forecast.values]
band_y = {level: (np.r_[filling.loc[end], forecast.values + lo], np.r_[filling.loc[end], forecast.values + hi])
          for level, (lo, hi) in bands.items()}


def forecast_traces(k):
    """The traces that change between frames: the bands and the forecast for the first k weeks."""
    traces = []
    for level, opacity in [(0.9, 0.14), (0.8, 0.25)]:
        if level not in band_y:
            continue
        lower, upper = band_y[level]
        traces.append(go.Scatter(x=x_fc[:k + 1], y=upper[:k + 1], mode="lines", line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        traces.append(go.Scatter(x=x_fc[:k + 1], y=lower[:k + 1], mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=f"rgba(235,104,52,{opacity})", name=f"{level:.0%} interval",
                                 hoverinfo="skip"))
    traces.append(go.Scatter(x=x_fc[:k + 1], y=y_fc[:k + 1], mode="lines+markers", name="Forecast",
                             line=dict(color=FORECAST, width=3), marker=dict(size=6),
                             hovertemplate="%{y:.1f} %<extra>Forecast</extra>"))
    return traces


static = [
    go.Scatter(x=shown.index, y=shown, name="Filling (training data)", line=dict(color=HISTORY, width=2),
               hovertemplate="%{y:.1f} %<extra>Filling</extra>"),
    go.Scatter(x=actual.index, y=actual, name="What really happened", line=dict(color=ACTUAL, width=2, dash="dash"),
               hovertemplate="%{y:.1f} %<extra>Actual</extra>"),
]
n_static = len(static)
fig = go.Figure(data=static + forecast_traces(horizon))
moving = list(range(n_static, len(fig.data)))
fig.frames = [go.Frame(data=forecast_traces(k), traces=moving, name=str(k)) for k in range(1, horizon + 1)]

values = np.concatenate([shown.values, y_fc, *[np.concatenate(b) for b in band_y.values()],
                         actual.dropna().values])
low, high = np.nanmin(values), np.nanmax(values)
pad = (high - low) * 0.08 + 1
play = dict(frame=dict(duration=180, redraw=False), transition=dict(duration=0), fromcurrent=False, mode="immediate")
fig.update_layout(
    height=520, hovermode="x unified", margin=dict(t=40, b=40),
    yaxis=dict(title="Filling (%)", range=[max(low - pad, 0), min(high + pad, 100)]),
    xaxis=dict(range=[shown.index[0], future_dates[-1] + pd.Timedelta(days=4)]),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    updatemenus=[dict(type="buttons", direction="left", x=0, y=-0.12, xanchor="left", yanchor="top",
                      buttons=[dict(label="▶ Play", method="animate", args=[None, play]),
                               dict(label="❚❚ Pause", method="animate",
                                    args=[[None], dict(frame=dict(duration=0), mode="immediate")])])],
    sliders=[dict(active=horizon - 1, x=0.16, y=-0.07, len=0.84, currentvalue=dict(prefix="Weeks ahead: "),
                  steps=[dict(label=str(k), method="animate",
                              args=[[str(k)], dict(frame=dict(duration=0, redraw=False), mode="immediate")])
                         for k in range(1, horizon + 1)])],
)
st.plotly_chart(fig)

if interval_method == QUANTILE:
    interval_text = (
        "The intervals come from four extra SARIMAX models with the same settings, trained with quantile loss "
        "(alpha 0.05, 0.10, 0.90 and 0.95). They give the 80 % and 90 % interval one week ahead, which is widened "
        "for later weeks by the number of weeks ahead to the power 0.75. In the notebook tests the 90 % band held "
        "the real filling 87–90 % of the time.")
elif n_past:
    interval_text = (
        f"The intervals come from the model's own errors when it forecast {horizon} weeks ahead from {n_past} "
        "earlier weeks in the training period (every 4 weeks): 80 % and 90 % of those errors fall inside the bands.")
else:
    interval_text = "Too little training data for intervals (they need forecasts from earlier weeks)."
st.caption(
    f"Training: {start:%d.%m.%Y}–{end:%d.%m.%Y} ({len(filling.loc[start:end])} weeks). "
    f"Exogenous: {', '.join(exog_labels) or 'none'}. Fitting and forecasting took {seconds:.2f} s. {interval_text}"
)

with st.expander("Forecast table"):
    table = pd.DataFrame({"Forecast (%)": forecast.round(1)})
    for level in sorted(bands):
        lo, hi = bands[level]
        table[f"{level:.0%} lower"] = (forecast + lo).clip(0, 100).round(1)
        table[f"{level:.0%} upper"] = (forecast + hi).clip(0, 100).round(1)
    if actual.notna().any():
        table["Actual (%)"] = actual.round(1)
    table.index = table.index.strftime("%d.%m.%Y")
    st.dataframe(table)
