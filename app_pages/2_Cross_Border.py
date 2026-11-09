import calendar

import pandas as pd
import plotly.express as px
import streamlit as st

from mongo_utils import load_crossborder

st.set_page_config(page_title="Cross-border flows", layout="wide")
st.title("Cross-border electricity flows")

# the daily data the notebook made with Spark and stored in MongoDB
df = load_crossborder()

if df.empty:
    # shown until the notebook has filled the MongoDB collection
    st.info("No cross-border data in MongoDB yet. Run the ENTSO-E part of the notebook first.")
    load_crossborder.clear()  # don't keep the empty result cached, so new data shows up right away
    st.stop()

connections = sorted(df["connection"].unique())
years = sorted(df["date"].dt.year.unique(), reverse=True)  # newest year first

left, right = st.columns(2)

# ---- left: pie chart for one connection and one year ----
with left:
    st.subheader("Total flow for one year")
    connection = st.radio("Connection", connections, horizontal=True)
    # a different control from the radio buttons: a dropdown for the year
    year = st.selectbox("Year", years)

    one_year = df[(df["connection"] == connection) & (df["date"].dt.year == year)]
    totals_twh = one_year.groupby("direction")["flow_mwh"].sum() / 1e6  # MWh -> TWh

    fig = px.pie(
        names=totals_twh.index,
        values=totals_twh.values,
        title=f"{connection}, {year}",
    )
    fig.update_traces(
        texttemplate="%{label}<br>%{value:.2f} TWh<br>%{percent}",
        hovertemplate="%{label}: %{value:.2f} TWh<extra></extra>",
        showlegend=False,
    )
    st.plotly_chart(fig)

    # the current year is not over, so its total only covers the days so far
    last_day = one_year["date"].max()
    if year == pd.Timestamp.now().year:
        st.caption(f"{year} is not complete; data up to {last_day:%d.%m.%Y}.")

# ---- right: line plot for any set of months in the chosen year ----
with right:
    st.subheader("Daily flow by month")
    # pills let the user switch any number of months on and off; January by default
    months = st.pills(
        "Months",
        options=list(range(1, 13)),
        selection_mode="multi",
        default=[1],
        format_func=lambda m: calendar.month_abbr[m],
    )
    # filter which flows are drawn: all connections or just one, in one or both directions
    line_connection = st.selectbox("Connection", ["All connections"] + connections, key="line_connection")
    chosen_connections = connections if line_connection == "All connections" else [line_connection]
    directions = st.segmented_control(
        "Direction",
        options=["out of Norway", "into Norway"],
        selection_mode="multi",
        default=["out of Norway", "into Norway"],
    )

    if not months:
        st.info("Choose at least one month.")
    elif not directions:
        st.info("Choose at least one direction.")
    else:
        year_days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        flows = df[
            (df["date"].dt.year == year)
            & df["connection"].isin(chosen_connections)
            & df["direction"].isin(directions)
        ]
        lines = []
        for (conn, direction), g in flows.groupby(["connection", "direction"]):
            # put the values on a full calendar and blank out the months that are not chosen,
            # so the line breaks at the gaps instead of joining e.g. January straight to March
            s = g.set_index("date")["flow_mwh"].reindex(year_days)
            s[~s.index.month.isin(months)] = float("nan")
            lines.append(pd.DataFrame({"date": s.index, "flow_gwh": s.values / 1000, "flow": f"{conn} ({direction})"}))

        if not lines:
            st.info(f"No data for this choice in {year}.")
        else:
            fig = px.line(
                pd.concat(lines),
                x="date",
                y="flow_gwh",
                color="flow",
                title=f"Daily cross-border flow, {year}",
                labels={"date": "Date", "flow_gwh": "Flow (GWh per day)", "flow": "Flow"},
            )
            # zoom the x-axis to the chosen months, and put the legend below the plot
            first, last = min(months), max(months)
            fig.update_xaxes(range=[pd.Timestamp(year, first, 1), pd.Timestamp(year, last, 1) + pd.offsets.MonthEnd(1)])
            fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2))
            st.plotly_chart(fig)

# ---- below the columns: where the data comes from ----
with st.expander("About the data"):
    st.markdown(
        "- **Source:** ENTSO-E Transparency Platform, *Physical Flows* between bidding zones, "
        "fetched with the `entsoe-py` library.\n"
        "- **Connections:** every link between a Norwegian price area (NO_1–NO_5) and a "
        "neighbouring zone. Each connection is counted in both directions: *out of Norway* and "
        "*into Norway*.\n"
        "- **Processing:** hourly values were stored in a local Cassandra database, read with "
        "Spark, summed to daily totals (Norwegian calendar days) and saved to MongoDB, which "
        "this page reads from.\n"
        "- **Units:** MWh per day in the database; shown as TWh in the pie chart and GWh per day "
        "in the line plot."
    )