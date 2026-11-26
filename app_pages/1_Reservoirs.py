import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data_utils import AREA_TYPES, AREAS, load_data, numeric_columns
from utils.explore_views import outlier_view, stl_spectrogram_view
from utils.sources import show_source_info

# One page for the reservoir data (NVE Magasinstatistikk), with a tab for each way of looking at it.
# It replaces the old "Data Table" and "Plot" pages from part 1 and the separate STL page: the area
# is chosen once in the sidebar and used by every tab.
st.set_page_config(page_title="Reservoirs", layout="wide")
area = st.session_state["area"]
st.title(f"Reservoirs in {AREAS[area]}")
show_source_info("reservoir")

this_year = pd.Timestamp.now().year


# ---- tab 1: the raw data, filtered by years and measurement ----
def explore_tab():
    # All areas of the same type are shown, so the chosen area can be compared with the others.
    area_type = area.split()[0]
    # the range is fixed (NVE's data starts in 1995), so the slider can be drawn before any download
    start_year, end_year = st.slider("Years", min_value=1995, max_value=this_year,
                                     value=(this_year - 4, this_year), key="reservoir_years")
    df = load_data(start_year, end_year)  # only the chosen years (see load_data in data_utils.py)
    df = df[df["area_type"] == area_type]

    # the measurement to show; fill_ratio first, since it is the most useful one
    cols = numeric_columns(df)
    cols = ["fill_ratio"] + [c for c in cols if c != "fill_ratio"]
    column = st.selectbox("Measurement", cols, key="reservoir_measurement")
    is_ratio = "ratio" in column  # ratios are shown as percent
    st.caption(f"{df['area'].nunique()} area(s), {df['date'].min():%d.%m.%Y} to {df['date'].max():%d.%m.%Y}")

    plot_tab, table_tab = st.tabs(["Plot", "Table"])
    with plot_tab:
        fig = px.line(df, x="date", y=column, color="area",
                      title=f"{column} for {AREA_TYPES[area_type]}, {start_year}–{end_year}",
                      labels={"date": "Date", "area": "Area"})
        if is_ratio:
            fig.update_yaxes(tickformat=".0%", hoverformat=".1%")
        # the area chosen in the sidebar is drawn thicker than the others
        fig.for_each_trace(lambda t: t.update(line_width=3 if t.name == area else 1.2))
        fig.update_layout(hovermode="x unified")  # hovering shows every area's value for that week
        st.plotly_chart(fig)

    # one row per area, with the trend drawn inside the table
    with table_tab:
        table = df.groupby("area").agg(
            capacity_twh=("capacity_twh", "last"),
            latest=(column, "last"),
            trend=(column, list),  # all values in the chosen years, drawn by LineChartColumn
        ).reset_index()
        st.dataframe(
            table,
            column_config={
                "area": "Area",
                "capacity_twh": st.column_config.NumberColumn("Capacity (TWh)", format="%.1f"),
                "latest": st.column_config.NumberColumn(f"Latest {column}", format="percent" if is_ratio else "%.2f"),
                "trend": st.column_config.LineChartColumn(f"{column}, {start_year}–{end_year}"),
            },
            hide_index=True,
            width="stretch",
        )


# ---- tab 2: STL and spectrogram of the whole weekly history ----
def stl_tab():
    df = load_data()
    fill = df[df["area"] == area].set_index("date")["fill_ratio"] * 100
    st.caption(f"Weekly fill ratio from NVE, {fill.index.min():%d.%m.%Y} to {fill.index.max():%d.%m.%Y} "
               f"({len(fill):,} weeks).")
    # the yearly cycle is 52 weeks: the reservoirs empty through the winter and fill when the snow melts
    stl_spectrogram_view(
        fill, "Fill ratio", "%", period=52, samples_per_year=52, step="week", key="reservoir_stl",
        cycle_note="The yearly filling and emptying of the reservoirs is at 1 cycle per year.",
    )


# ---- tab 3: outliers and anomalies in the weekly values ----
def outlier_tab():
    df = load_data()
    start_year, end_year = st.select_slider("Years", options=list(range(1995, this_year + 1)),
                                            value=(this_year - 4, this_year), key="reservoir_outlier_years")
    weekly = df[(df["area"] == area) & df["date"].dt.year.between(start_year, end_year)].set_index("date")
    # The weekly change is the default: a week where the filling rises or falls much more than normal
    # for the season (a big melt, a dry spell, heavy production) stands out there, while the fill
    # ratio itself mostly follows the slow yearly cycle.
    frame = pd.DataFrame({
        "fill_ratio_change": weekly["fill_ratio_change"] * 100,
        "fill_ratio": weekly["fill_ratio"] * 100,
        "filling_twh": weekly["filling_twh"],
    })
    if len(frame) < 30:
        st.warning("Too few weeks. Choose more years.")
        return
    st.caption(f"Weekly data from NVE, {frame.index.min():%d.%m.%Y} to {frame.index.max():%d.%m.%Y} ({len(frame)} weeks).")
    variables = {
        "fill_ratio_change": ("Weekly change in fill ratio", "pp"),
        "fill_ratio": ("Fill ratio", "%"),
        "filling_twh": ("Filling", "TWh"),
    }
    outlier_view(frame, variables, spc_default="fill_ratio_change", lof_default="fill_ratio_change",
                 step="week", period_text=f"{start_year}–{end_year}", key="reservoir")


# on_change="rerun" makes the tabs lazy: only the open tab's code runs, so a tab never downloads or
# computes anything until the user opens it
tabs = st.tabs(["Explore the data", "STL and spectrogram", "Outliers and anomalies"],
               key="reservoir_tab", on_change="rerun")
for tab, content in zip(tabs, [explore_tab, stl_tab, outlier_tab]):
    if tab.open:
        with tab:
            content()
