import calendar

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data_utils import AREAS
from utils.explore_views import outlier_view, stl_spectrogram_view
from utils.mongo_utils import crossborder_for_area, load_crossborder
from utils.sources import show_source_info

# One page for the cross-border flows (ENTSO-E, stored in MongoDB by the notebook), with a tab for
# each way of looking at them.
st.set_page_config(page_title="Cross-border flows", layout="wide")
area = st.session_state["area"]
st.title("Cross-border electricity flows")
show_source_info("crossborder")

# the daily data the notebook made with Spark and stored in MongoDB
df = load_crossborder()
if df.empty:
    # shown until the notebook has filled the MongoDB collection
    st.info("No cross-border data in MongoDB yet. Run the ENTSO-E part of the notebook first.")
    load_crossborder.clear()  # don't keep the empty result cached, so new data shows up right away
    st.stop()

FLOWS = {
    "net_export_gwh": ("Net export", "GWh"),
    "export_gwh": ("Export (out of Norway)", "GWh"),
    "import_gwh": ("Import (into Norway)", "GWh"),
}


# the flows of the area chosen in the sidebar, one row per day (used by the analysis tabs)
def area_daily():
    daily = crossborder_for_area(df, area)
    if daily.empty:
        st.info(f"{AREAS[area]} has no connections abroad. Choose Norway, a water area or another price area.")
        return None
    scope = "the area's own connections" if area.startswith("EL") else "all connections"
    return daily, scope


# ---- tab 1: the raw data, filtered by connection, year, months and direction ----
def explore_tab():
    connections = sorted(df["connection"].unique())
    years = sorted(df["date"].dt.year.unique(), reverse=True)  # newest year first
    left, right = st.columns(2)

    # left: pie chart for one connection and one year
    with left:
        st.subheader("Total flow for one year")
        connection = st.radio("Connection", connections, horizontal=True, key="crossborder_connection")
        # a different control from the radio buttons: a dropdown for the year
        year = st.selectbox("Year", years, key="crossborder_year")
        one_year = df[(df["connection"] == connection) & (df["date"].dt.year == year)]
        totals_twh = one_year.groupby("direction")["flow_mwh"].sum() / 1e6  # MWh -> TWh
        fig = px.pie(names=totals_twh.index, values=totals_twh.values, title=f"{connection}, {year}")
        fig.update_traces(texttemplate="%{label}<br>%{value:.2f} TWh<br>%{percent}",
                          hovertemplate="%{label}: %{value:.2f} TWh<extra></extra>", showlegend=False)
        st.plotly_chart(fig)
        # the current year is not over, so its total only covers the days so far
        if year == pd.Timestamp.now().year:
            st.caption(f"{year} is not complete; data up to {one_year['date'].max():%d.%m.%Y}.")

    # right: line plot for any set of months in the chosen year
    with right:
        st.subheader("Daily flow by month")
        # pills let the user switch any number of months on and off; January by default
        months = st.pills("Months", options=list(range(1, 13)), selection_mode="multi", default=[1],
                          format_func=lambda m: calendar.month_abbr[m], key="crossborder_months")
        # filter which flows are drawn: all connections or just one, in one or both directions
        line_connection = st.selectbox("Connection", ["All connections"] + connections, key="line_connection")
        chosen_connections = connections if line_connection == "All connections" else [line_connection]
        directions = st.segmented_control("Direction", options=["out of Norway", "into Norway"],
                                          selection_mode="multi", default=["out of Norway", "into Norway"],
                                          key="crossborder_directions")
        if not months:
            st.info("Choose at least one month.")
            return
        if not directions:
            st.info("Choose at least one direction.")
            return
        year_days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        flows = df[(df["date"].dt.year == year) & df["connection"].isin(chosen_connections)
                   & df["direction"].isin(directions)]
        lines = []
        for (conn, direction), g in flows.groupby(["connection", "direction"]):
            # put the values on a full calendar and blank out the months that are not chosen,
            # so the line breaks at the gaps instead of joining e.g. January straight to March
            s = g.set_index("date")["flow_mwh"].reindex(year_days)
            s[~s.index.month.isin(months)] = float("nan")
            lines.append(pd.DataFrame({"date": s.index, "flow_gwh": s.values / 1000, "flow": f"{conn} ({direction})"}))
        if not lines:
            st.info(f"No data for this choice in {year}.")
            return
        fig = px.line(pd.concat(lines), x="date", y="flow_gwh", color="flow",
                      title=f"Daily cross-border flow, {year}",
                      labels={"date": "Date", "flow_gwh": "Flow (GWh per day)", "flow": "Flow"})
        # zoom the x-axis to the chosen months, and put the legend below the plot
        first, last = min(months), max(months)
        fig.update_xaxes(range=[pd.Timestamp(year, first, 1), pd.Timestamp(year, last, 1) + pd.offsets.MonthEnd(1)])
        fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2))
        st.plotly_chart(fig)


# ---- tab 2: STL and spectrogram of the area's daily flow ----
def stl_tab():
    found = area_daily()
    if found is None:
        return
    daily, scope = found
    column = st.selectbox("Flow", list(FLOWS), format_func=lambda c: FLOWS[c][0], key="crossborder_stl_flow")
    st.caption(f"Daily totals for {AREAS[area]} over {scope}, {daily.index.min():%d.%m.%Y} to "
               f"{daily.index.max():%d.%m.%Y} ({len(daily)} days).")
    # The data only covers a few years, too little for a yearly STL period. Power use and trade follow
    # the working week, so the STL uses a weekly period (7 days) on the daily values instead.
    stl_spectrogram_view(
        daily[column], FLOWS[column][0], "GWh per day", period=7, samples_per_year=365, step="day",
        key="crossborder_stl", window=(28, 365, 91, 7), max_frequency=(2, 182, 60),
        cycle_note="The weekly pattern (weekdays and weekends) is at 52 cycles per year, the yearly cycle at 1.",
    )


# ---- tab 3: outliers and anomalies in the area's daily flow, one year at a time ----
def outlier_tab():
    found = area_daily()
    if found is None:
        return
    daily, scope = found
    # one year at a time, like the weather, so the seasonal curve of the SPC fits the year
    year = st.selectbox("Year", sorted(daily.index.year.unique(), reverse=True), key="crossborder_outlier_year")
    frame = daily[daily.index.year == year]
    st.caption(f"Daily totals for {AREAS[area]} over {scope}, {frame.index.min():%d.%m.%Y} to {frame.index.max():%d.%m.%Y}.")
    outlier_view(frame, FLOWS, spc_default="net_export_gwh", lof_default="import_gwh",
                 step="day", period_text=str(year), key="crossborder")


# on_change="rerun" makes the tabs lazy: only the open tab's code runs
tabs = st.tabs(["Explore the data", "STL and spectrogram", "Outliers and anomalies"],
               key="crossborder_tab", on_change="rerun")
for tab, content in zip(tabs, [explore_tab, stl_tab, outlier_tab]):
    if tab.open:
        with tab:
            content()
