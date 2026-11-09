import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from analysis_utils import spectrogram_weekly, stl_decompose
from data_utils import AREAS, load_data

st.set_page_config(page_title="STL and spectrogram", layout="wide")

# the area comes from the global selector in the sidebar; the analysis settings are local to each tab
area = st.session_state["area"]
st.title(f"Degree of filling for {AREAS[area]}")

df = load_data()
fill = df[df["area"] == area].set_index("date")["fill_ratio"]
st.caption(f"Weekly data from NVE, {fill.index.min():%d.%m.%Y} to {fill.index.max():%d.%m.%Y} ({len(fill):,} weeks).")

stl_tab, spectrogram_tab = st.tabs(["STL decomposition", "Spectrogram"])

# ---- STL ----
with stl_tab:
    c1, c2, c3 = st.columns(3)
    seasonal = c1.slider("Seasonal smoother (years)", 7, 51, 13, step=2,
                         help="How fast the yearly pattern can change. Odd, at least 7.")
    trend = c2.slider("Trend smoother (weeks)", 53, 313, 105, step=2,
                      help="Longer gives a smoother trend. Odd and longer than 52 weeks.")
    robust = c3.toggle("Robust", value=True, help="Give less weight to unusual weeks.")

    parts = stl_decompose(fill, seasonal=seasonal, trend=trend, robust=robust)

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        subplot_titles=list(parts.columns))
    for row, name in enumerate(parts.columns, start=1):
        fig.add_trace(go.Scatter(x=parts.index, y=parts[name], name=name,
                                 line=dict(color="#2a78d6", width=1)), row=row, col=1)
        if name in ("Seasonal", "Residual"):
            fig.add_hline(y=0, line_color="#b5b4ad", line_width=1, row=row, col=1)
    fig.update_layout(height=800, showlegend=False, hovermode="x unified",
                      title=f"STL (period 52 weeks, seasonal={seasonal}, trend={trend}, robust={robust})")
    st.plotly_chart(fig)
    st.caption(
        "Observed = trend + seasonal + residual. The last values of the trend are uncertain, "
        "because there is no data after them."
    )

# ---- spectrogram ----
with spectrogram_tab:
    c1, c2, c3 = st.columns(3)
    window = c1.slider("Window length (weeks)", 52, 520, 156, step=26,
                       help="Longer gives sharper frequencies but less detail in time.")
    overlap = c2.slider("Window overlap (weeks)", 0, window - 1, window * 5 // 6,  # 130 for 156
                        help="Weeks each window shares with the next one.")
    max_frequency = c3.slider("Highest frequency shown (cycles per year)", 2, 26, 6)

    frequencies, centres, power_db = spectrogram_weekly(fill, window=window, overlap=overlap)
    shown = frequencies <= max_frequency

    fig = go.Figure(go.Heatmap(
        x=centres, y=frequencies[shown], z=power_db[shown],
        colorscale="Blues", zmax=power_db.max(), zmin=power_db.max() - 50,  # the top 50 dB
        colorbar=dict(title="Power (dB)"),
        hovertemplate="%{x|%Y-%m}<br>%{y:.2f} cycles per year<br>%{z:.1f} dB<extra></extra>",
    ))
    fig.update_layout(height=500, xaxis_title="Date (centre of the window)",
                      yaxis_title="Frequency (cycles per year)",
                      title=f"Spectrogram (window {window} weeks, overlap {overlap} weeks)")
    st.plotly_chart(fig)
    st.caption(
        f"Frequency resolution: {52 / window:.2f} cycles per year. "
        "The yearly filling and emptying of the reservoirs is at 1 cycle per year."
    )
