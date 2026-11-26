"""The analysis views shared by the Explore pages: STL and spectrogram, and outliers and anomalies.

Each data source (reservoirs, weather, cross-border flows) has its own page that loads its data and
then calls these functions, so the three sources are analysed and drawn the same way. All plots are
Plotly, with the app's colours.
"""
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.analysis_utils import lof_anomalies, spc_outliers, spectrogram_series, stl_decompose

LINE, BOUNDARY, OUTLIER, ZERO = "#2a78d6", "#8a8984", "#eb6834", "#b5b4ad"


def _odd(n):
    return n if n % 2 else n + 1


# ---- STL and spectrogram ----
# series: one regular time series (weekly or daily). period: the season length in steps
# (52 for weekly data with a yearly cycle, 7 for daily data with a weekly cycle).
# samples_per_year: 52 for weekly data, 365 for daily data. step: "week" or "day".
def stl_spectrogram_view(series, name, unit, period, samples_per_year, step, key,
                         window=(52, 520, 156, 26), max_frequency=(2, 26, 6), cycle_note=""):
    series = series.dropna()
    if len(series) < 2 * period + 1:
        st.warning(f"Too little data for STL: at least {2 * period + 1} {step}s are needed. Choose more years.")
        return
    stl_tab, spectrogram_tab = st.tabs(["STL decomposition", "Spectrogram"])

    with stl_tab:
        c1, c2, c3 = st.columns(3)
        seasonal = c1.slider("Seasonal smoother", 7, 51, 13, step=2, key=f"{key}_seasonal",
                             help=f"How many seasons ({period} {step}s each) the seasonal pattern is smoothed over. "
                                  "Odd, at least 7. Smaller lets the pattern change faster.")
        trend_min = _odd(period + 1)
        trend = c2.slider(f"Trend smoother ({step}s)", trend_min, _odd(period * 6), _odd(period * 2), step=2,
                          key=f"{key}_trend", help=f"Longer gives a smoother trend. Odd and longer than {period} {step}s.")
        robust = c3.toggle("Robust", value=True, key=f"{key}_robust", help=f"Give less weight to unusual {step}s.")

        parts = stl_decompose(series, seasonal=seasonal, trend=trend, robust=robust, period=period)
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                            subplot_titles=list(parts.columns))
        for row, part in enumerate(parts.columns, start=1):
            fig.add_trace(go.Scatter(x=parts.index, y=parts[part], name=part,
                                     line=dict(color=LINE, width=1)), row=row, col=1)
            if part in ("Seasonal", "Residual"):
                fig.add_hline(y=0, line_color=ZERO, line_width=1, row=row, col=1)
        fig.update_layout(height=800, showlegend=False, hovermode="x unified",
                          title=f"{name} ({unit}): STL with period {period} {step}s")
        fig.update_traces(hovertemplate="%{y:.2f}")
        st.plotly_chart(fig)
        st.caption("Observed = trend + seasonal + residual. The last values of the trend are uncertain, "
                   "because there is no data after them.")

    with spectrogram_tab:
        low, high, default, window_step = window
        high = min(high, len(series))
        c1, c2, c3 = st.columns(3)
        length = c1.slider(f"Window length ({step}s)", low, high, min(default, high), step=window_step,
                           key=f"{key}_window", help="Longer gives sharper frequencies but less detail in time.")
        overlap = c2.slider(f"Window overlap ({step}s)", 0, length - 1, length * 5 // 6, key=f"{key}_overlap",
                            help=f"{step.capitalize()}s each window shares with the next one.")
        top = c3.slider("Highest frequency shown (cycles per year)", *max_frequency, key=f"{key}_top")

        frequencies, centres, power_db = spectrogram_series(series, length, overlap, samples_per_year)
        shown = frequencies <= top
        fig = go.Figure(go.Heatmap(
            x=centres, y=frequencies[shown], z=power_db[shown],
            colorscale="Blues", zmax=power_db.max(), zmin=power_db.max() - 50,  # the top 50 dB
            colorbar=dict(title="Power (dB)"),
            hovertemplate="%{x|%Y-%m}<br>%{y:.2f} cycles per year<br>%{z:.1f} dB<extra></extra>",
        ))
        fig.update_layout(height=500, xaxis_title="Date (centre of the window)",
                          yaxis_title="Frequency (cycles per year)",
                          title=f"{name}: spectrogram (window {length} {step}s, overlap {overlap} {step}s)")
        st.plotly_chart(fig)
        st.caption(f"Frequency resolution: {samples_per_year / length:.2f} cycles per year. {cycle_note}")


# ---- outliers (SPC on the SATV) and anomalies (LOF) ----
# frame: one column per variable, one row per step. variables: {column: (name, unit)}.
def outlier_view(frame, variables, spc_default, lof_default, step, period_text, key):
    plural = f"{step}s"
    nearby = "two weeks" if step == "day" else "15 weeks"  # the 15 steps around each point

    def variable_selector(default, widget_key):
        options = [v for v in variables if v in frame.columns]
        return st.selectbox("Property", options, index=options.index(default), key=widget_key,
                            format_func=lambda v: variables[v][0])

    spc_tab, lof_tab = st.tabs(["Outliers (SATV and SPC)", "Anomalies (LOF)"])

    with spc_tab:
        c1, c2, c3 = st.columns(3)
        with c1:
            column = variable_selector(spc_default, f"{key}_spc_variable")
        cutoff = c2.slider("DCT cutoff (coefficients)", 2, 60, 10, key=f"{key}_cutoff",
                           help="The first coefficients are the seasonal curve. Higher follows the data more closely.")
        n_std = c3.slider("Number of robust standard deviations", 1.0, 6.0, 3.0, step=0.5, key=f"{key}_nstd")
        name, unit = variables[column]
        series = frame[column].dropna()

        result, summary = spc_outliers(series, cutoff=cutoff, n_std=n_std)
        outliers = result[result["is_outlier"]]
        m1, m2, m3 = st.columns(3)
        m1.metric("Outliers", f"{summary['outliers']} of {summary['days']} {plural}",
                  f"{summary['above']} above, {summary['below']} below", delta_color="off")
        m2.metric("Seasonal curve holds cycles", f"> {summary['seasonal_cycles_longer_than_days']:.0f} {plural}")
        m3.metric("Robust SD (SATV)", f"{summary['satv_robust_sd']:.2f} {unit}")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=result.index, y=result["value"], name=name, line=dict(color=LINE, width=1)))
        fig.add_trace(go.Scatter(x=result.index, y=result["upper"], name=f"SPC boundaries (±{n_std:g} robust SD)",
                                 line=dict(color=BOUNDARY, width=1, dash="dash")))
        fig.add_trace(go.Scatter(x=result.index, y=result["lower"], name="Lower boundary", showlegend=False,
                                 line=dict(color=BOUNDARY, width=1, dash="dash")))
        fig.add_trace(go.Scatter(x=outliers.index, y=outliers["value"], mode="markers",
                                 name=f"Outliers ({len(outliers)})",
                                 marker=dict(color=OUTLIER, size=9, line=dict(color="white", width=1))))
        fig.update_layout(height=480, hovermode="x unified", yaxis_title=f"{name} ({unit})", xaxis_title="Date",
                          title=f"{name}, {period_text}: outliers outside the SPC boundaries",
                          legend=dict(orientation="h", yanchor="bottom", y=1.0))
        st.plotly_chart(fig)

        st.subheader(f"Outlier {plural}")
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
                f"1. A Discrete Cosine Transform (DCT) splits the series into cosines. The first `cutoff` "
                f"coefficients (cycles longer than {summary['seasonal_cycles_longer_than_days']:.0f} {plural}) "
                "make up the seasonal curve.\n"
                "2. The data minus the seasonal curve is the seasonally adjusted variation (SATV).\n"
                "3. The boundaries are the seasonal curve + the median of the SATV ± the chosen number of robust "
                "standard deviations (MAD × 1.4826), so the outliers themselves do not widen the boundaries."
            )

    with lof_tab:
        c1, c2, c3 = st.columns(3)
        with c1:
            column = variable_selector(lof_default, f"{key}_lof_variable")
        proportion = c2.slider("Proportion of outliers (%)", 0.5, 10.0, 1.0, step=0.5, key=f"{key}_proportion") / 100
        n_neighbors = c3.slider("Number of neighbours", 5, 60, 20, key=f"{key}_neighbours",
                                help=f"How many nearby {plural} each {step} is compared with.")
        name, unit = variables[column]
        series = frame[column].dropna()

        result, summary = lof_anomalies(series, proportion=proportion, n_neighbors=n_neighbors)
        outliers = result[result["is_outlier"]]
        m1, m2, m3 = st.columns(3)
        m1.metric("Anomalies", f"{summary['outliers']} of {summary['days']} {plural}",
                  f"{summary['higher']} higher, {summary['lower']} lower than nearby {plural}", delta_color="off")
        m2.metric("Largest difference", f"{summary['largest_difference']:.1f} {unit}",
                  f"from the {nearby} around it", delta_color="off")
        m3.metric("LOF score threshold", f"{summary['lof_threshold']:.2f}", "about 1 is normal", delta_color="off")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=result.index, y=result["value"], name=name, line=dict(color=LINE, width=1)))
        fig.add_trace(go.Scatter(x=outliers.index, y=outliers["value"], mode="markers",
                                 name=f"LOF anomalies ({len(outliers)})",
                                 marker=dict(color=OUTLIER, size=9, line=dict(color="white", width=1)),
                                 customdata=outliers["lof_score"],
                                 hovertemplate="%{y:.1f}, LOF score %{customdata:.2f}<extra></extra>"))
        fig.update_layout(height=480, hovermode="x unified", yaxis_title=f"{name} ({unit})", xaxis_title="Date",
                          title=f"{name}, {period_text}: anomalies by Local Outlier Factor",
                          legend=dict(orientation="h", yanchor="bottom", y=1.0))
        st.plotly_chart(fig)

        st.subheader(f"Anomalous {plural}")
        st.dataframe(
            outliers.sort_values("lof_score", ascending=False)[["value", "local_median", "difference", "lof_score", "direction"]],
            column_config={
                "_index": st.column_config.DateColumn("Date", format="D MMM YYYY"),
                "value": st.column_config.NumberColumn(f"{name} ({unit})", format="%.1f"),
                "local_median": st.column_config.NumberColumn(f"Median of the {nearby} around", format="%.1f"),
                "difference": st.column_config.NumberColumn("Difference", format="%+.1f"),
                "lof_score": st.column_config.NumberColumn("LOF score", format="%.2f"),
                "direction": f"Compared with nearby {plural}",
            },
        )
        with st.expander("How it works"):
            st.markdown(
                f"Local Outlier Factor compares how close each point is to its nearest neighbours with how close "
                f"those neighbours are to theirs. Each {step} is a point with two standardised features, the date "
                f"and the value, so a {step} is an anomaly when it is very different from the {plural} around it.\n\n"
                "The proportion decides how many points are marked (LOF's `contamination`)."
            )
