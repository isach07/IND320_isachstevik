import calendar

import matplotlib.pyplot as plt
import pandas as pd
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

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.pie(
        totals_twh,
        labels=[f"{d}\n{v:.2f} TWh" for d, v in totals_twh.items()],
        autopct="%1.0f%%",
        startangle=90,
    )
    ax.set_title(f"{connection}, {year}")
    st.pyplot(fig)

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

    if not months:
        st.info("Choose at least one month.")
    else:
        fig, ax = plt.subplots(figsize=(7, 5))
        year_days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
        for (conn, direction), g in df[df["date"].dt.year == year].groupby(["connection", "direction"]):
            # put the values on a full calendar and blank out the months that are not chosen,
            # so the line breaks at the gaps instead of joining e.g. January straight to March
            s = g.set_index("date")["flow_mwh"].reindex(year_days)
            s[~s.index.month.isin(months)] = float("nan")
            ax.plot(s.index, s / 1000, label=f"{conn} ({direction})", linewidth=1)

        # zoom the x-axis to the chosen months
        first, last = min(months), max(months)
        ax.set_xlim(pd.Timestamp(year, first, 1), pd.Timestamp(year, last, 1) + pd.offsets.MonthEnd(1))
        ax.set_title(f"Daily cross-border flow, {year}")
        ax.set_xlabel("Date")
        ax.set_ylabel("Flow (GWh per day)")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, fontsize=7)
        fig.autofmt_xdate()
        st.pyplot(fig)

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