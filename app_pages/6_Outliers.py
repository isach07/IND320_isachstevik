import plotly.graph_objects as go
import streamlit as st

from analysis_utils import lof_anomalies, spc_outliers
from data_utils import AREAS
from weather_utils import ensure_weather, read_weather, weather_year_selector

st.set_page_config(page_title="Outliers and anomalies", layout="wide")

# the area comes from the global selector in the sidebar, the year is shared with the Weather page,
# and the analysis settings are local to each tab
area = st.session_state["area"]
st.title(f"Outliers and anomalies in the weather for {AREAS[area]}")

year = weather_year_selector()
status = ensure_weather(area, year)  # downloads anything missing (see weather_utils.py)
weather = read_weather(area, year)
if status["message"]:
    st.warning(status["message"])
if weather.empty:
    st.stop()

# one value per day: the average over the locations in the area
daily = weather.groupby("date").mean(numeric_only=True).drop(columns="point_id")
st.caption(
    f"Daily ERA5 data from Open-Meteo, average over {weather['point_id'].nunique()} locations, "
    f"{daily.index.min():%d.%m.%Y} to {daily.index.max():%d.%m.%Y}."
)

VARIABLES = {
    "precipitation_sum": ("Precipitation", "mm"),
    "rain_sum": ("Rain", "mm"),
    "snowfall_sum": ("Snowfall", "cm"),
    "temperature_2m_mean": ("Mean temperature", "°C"),
    "temperature_2m_max": ("Maximum temperature", "°C"),
    "temperature_2m_min": ("Minimum temperature", "°C"),
    "wind_speed_10m_mean": ("Mean wind speed", "m/s"),
}
LINE, BOUNDARY, OUTLIER = "#2a78d6", "#8a8984", "#eb6834"


def variable_selector(default, key):
    options = list(VARIABLES)
    return st.selectbox("Variable", options, index=options.index(default), key=key,
                        format_func=lambda v: VARIABLES[v][0])


spc_tab, lof_tab = st.tabs(["Outliers (SPC)", "Anomalies (LOF)"])

# ---- SPC: DCT high-pass filter and robust boundaries ----
with spc_tab:
    c1, c2, c3 = st.columns(3)
    with c1:
        column = variable_selector("precipitation_sum", key="spc_variable")
    cutoff = c2.slider("DCT cutoff (coefficients)", 2, 60, 10,
                       help="The first coefficients are the seasonal curve. Higher follows the data more closely.")
    n_std = c3.slider("Number of robust standard deviations", 1.0, 6.0, 3.0, step=0.5)
    name, unit = VARIABLES[column]

    result, summary = spc_outliers(daily[column], cutoff=cutoff, n_std=n_std)
    outliers = result[result["is_outlier"]]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Outliers", f"{summary['outliers']} of {summary['days']} days",
              f"{summary['above']} above, {summary['below']} below", delta_color="off")
    m2.metric("Seasonal cycles", f"> {summary['seasonal_cycles_longer_than_days']:.0f} days")
    m3.metric("Robust SD (SATV)", f"{summary['satv_robust_sd']:.2f} {unit}")
    if column.endswith("_sum"):
        m4.metric("Share of total on outlier days", f"{summary['share_of_total']:.0%}")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.index, y=result["value"], name=name, line=dict(color=LINE, width=1)))
    fig.add_trace(go.Scatter(x=result.index, y=result["upper"], name=f"SPC boundaries (±{n_std:g} robust SD)",
                             line=dict(color=BOUNDARY, width=1, dash="dash")))
    fig.add_trace(go.Scatter(x=result.index, y=result["lower"], name="Lower boundary", showlegend=False,
                             line=dict(color=BOUNDARY, width=1, dash="dash")))
    fig.add_trace(go.Scatter(x=outliers.index, y=outliers["value"], mode="markers", name=f"Outliers ({len(outliers)})",
                             marker=dict(color=OUTLIER, size=9, line=dict(color="white", width=1))))
    fig.update_layout(height=480, hovermode="x unified", yaxis_title=f"{name} ({unit})", xaxis_title="Date",
                      title=f"{name}, {year}: outliers outside the SPC boundaries",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0))
    st.plotly_chart(fig)

    st.subheader("Outlier days")
    st.dataframe(
        outliers.sort_values("value", ascending=False)[["value", "seasonal", "lower", "upper", "direction"]],
        column_config={
            "_index": st.column_config.DateColumn("Date", format="D MMM YYYY"),
            "value": st.column_config.NumberColumn(f"{name} ({unit})", format="%.1f"),
            "seasonal": st.column_config.NumberColumn("Seasonal curve", format="%.1f"),
            "lower": st.column_config.NumberColumn("Lower boundary", format="%.1f"),
            "upper": st.column_config.NumberColumn("Upper boundary", format="%.1f"),
            "direction": "Outside",
        },
    )
    with st.expander("How it works"):
        st.markdown(
            "1. A Discrete Cosine Transform (DCT) splits the daily series into cosines. The first "
            f"`cutoff` coefficients (cycles longer than {summary['seasonal_cycles_longer_than_days']:.0f} days) "
            "make up the seasonal curve.\n"
            "2. The data minus the seasonal curve is the seasonally adjusted variation (SATV), a high-pass "
            "filtered series. It is not plotted, only used for the boundaries.\n"
            "3. The boundaries are the seasonal curve + the median of the SATV ± the chosen number of robust "
            "standard deviations (MAD × 1.4826), estimated from the whole year, so the outliers themselves "
            "do not widen the boundaries.\n\n"
            "Precipitation cannot be negative, so the lower boundary is usually below 0 and only wet days "
            "become outliers."
        )

# ---- LOF: Local Outlier Factor on (date, value) ----
with lof_tab:
    c1, c2, c3 = st.columns(3)
    with c1:
        column = variable_selector("temperature_2m_mean", key="lof_variable")
    proportion = c2.slider("Proportion of outliers (%)", 0.5, 10.0, 1.0, step=0.5) / 100
    n_neighbors = c3.slider("Number of neighbours", 5, 60, 20,
                            help="How many nearby days each day is compared with.")
    name, unit = VARIABLES[column]

    result, summary = lof_anomalies(daily[column], proportion=proportion, n_neighbors=n_neighbors)
    outliers = result[result["is_outlier"]]

    m1, m2, m3 = st.columns(3)
    m1.metric("Anomalies", f"{summary['outliers']} of {summary['days']} days",
              f"{summary['higher']} higher, {summary['lower']} lower than nearby days", delta_color="off")
    m2.metric("Largest difference", f"{summary['largest_difference']:.1f} {unit}", "from the two weeks around it", delta_color="off")
    m3.metric("LOF score threshold", f"{summary['lof_threshold']:.2f}", "about 1 is normal", delta_color="off")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.index, y=result["value"], name=name, line=dict(color=LINE, width=1)))
    fig.add_trace(go.Scatter(x=outliers.index, y=outliers["value"], mode="markers", name=f"LOF anomalies ({len(outliers)})",
                             marker=dict(color=OUTLIER, size=9, line=dict(color="white", width=1)),
                             customdata=outliers["lof_score"],
                             hovertemplate="%{y:.1f}, LOF score %{customdata:.2f}<extra></extra>"))
    fig.update_layout(height=480, hovermode="x unified", yaxis_title=f"{name} ({unit})", xaxis_title="Date",
                      title=f"{name}, {year}: anomalies by Local Outlier Factor",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0))
    st.plotly_chart(fig)

    st.subheader("Anomalous days")
    st.dataframe(
        outliers.sort_values("lof_score", ascending=False)[["value", "local_median", "difference", "lof_score", "direction"]],
        column_config={
            "_index": st.column_config.DateColumn("Date", format="D MMM YYYY"),
            "value": st.column_config.NumberColumn(f"{name} ({unit})", format="%.1f"),
            "local_median": st.column_config.NumberColumn("Median of the two weeks around", format="%.1f"),
            "difference": st.column_config.NumberColumn("Difference", format="%+.1f"),
            "lof_score": st.column_config.NumberColumn("LOF score", format="%.2f"),
            "direction": "Compared with nearby days",
        },
    )
    with st.expander("How it works"):
        st.markdown(
            "Local Outlier Factor compares how close each point is to its nearest neighbours with how close "
            "those neighbours are to theirs. Each day is a point with two standardised features, the date "
            "and the value, so the neighbours are days close in both time and value. A day is an anomaly "
            "when it is very different from the days around it, not just because it is cold for the year.\n\n"
            "The proportion decides how many days are marked (LOF's `contamination`). The first and last "
            "days of the year only have neighbours on one side, so they are marked a little more easily."
        )
