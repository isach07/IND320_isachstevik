import pandas as pd
import plotly.express as px
import streamlit as st

from data_utils import AREA_TYPES, load_data, numeric_columns

# This page replaces the old "Data Table" and "Plot" pages from part 1.
# The controls are set once at the top and apply to both the plot and the table,
# so the user does not have to make the same choices on two pages.
st.set_page_config(page_title="Reservoirs", layout="wide")
st.title("Reservoir fill levels")

# ---- controls ----
left, right = st.columns([1, 2])

with left:
    # radio buttons choose which way Norway is split up; every area number of that type is shown
    area_type = st.radio(
        "Area type",
        options=list(AREA_TYPES),
        format_func=lambda t: AREA_TYPES[t],
    )

with right:
    # the slider decides which years are loaded from the NVE API.
    # the range is fixed (NVE's data starts in 1995), so it can be drawn before any download.
    this_year = pd.Timestamp.now().year
    start_year, end_year = st.slider(
        "Years to download",
        min_value=1995,
        max_value=this_year,
        value=(this_year - 4, this_year),  # last five years by default
    )

# only the chosen years are loaded (see load_data in data_utils.py)
df = load_data(start_year, end_year)
df = df[df["area_type"] == area_type]

# the measurement to show; fill_ratio first, since it is the most useful one
cols = numeric_columns(df)
cols = ["fill_ratio"] + [c for c in cols if c != "fill_ratio"]
column = st.selectbox("Measurement", cols)
is_ratio = "ratio" in column  # ratios are shown as percent

areas = sorted(df["area"].unique())
st.caption(f"{len(areas)} area(s), {df['date'].min():%d.%m.%Y} to {df['date'].max():%d.%m.%Y}")

plot_tab, table_tab = st.tabs(["Plot", "Table"])

# ---- plot: one line per area number ----
with plot_tab:
    fig = px.line(
        df,
        x="date",
        y=column,
        color="area",
        title=f"{column} for {AREA_TYPES[area_type]}, {start_year}–{end_year}",
        labels={"date": "Date", "area": "Area"},
    )
    if is_ratio:
        fig.update_yaxes(tickformat=".0%", hoverformat=".1%")
    fig.update_layout(hovermode="x unified")  # hovering shows every area's value for that week
    st.plotly_chart(fig)

# ---- table: one row per area number, with the trend drawn inside the table ----
with table_tab:
    table = df.groupby("area").agg(
        capacity_twh=("capacity_twh", "last"),
        latest=(column, "last"),
        trend=(column, list),  # all values in the chosen years, drawn by LineChartColumn
    ).reset_index()

    number_format = "percent" if is_ratio else "%.2f"
    st.dataframe(
        table,
        column_config={
            "area": "Area",
            "capacity_twh": st.column_config.NumberColumn("Capacity (TWh)", format="%.1f"),
            "latest": st.column_config.NumberColumn(f"Latest {column}", format=number_format),
            "trend": st.column_config.LineChartColumn(f"{column}, {start_year}–{end_year}"),
        },
        hide_index=True,
        width="stretch",
    )