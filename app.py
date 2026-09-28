import streamlit as st
import pandas as pd

st.set_page_config(page_title="IND320 Reservoirs", layout="wide")


@st.cache_data
def load_data():
    df = pd.read_csv("data/reservoirs.csv", parse_dates=["dato_Id"])
    df["area"] = df["omrType"] + " " + df["omrnr"].astype(str)
    return df.sort_values(["area", "dato_Id"])


def home():
    st.title("IND320 — Reservoir Data App")

    df = load_data()
    norway = df[df["area"] == "NO 0"]
    latest = norway.iloc[-1]
    # median fill ratio for the same week in earlier years
    same_week = norway[(norway["iso_uke"] == latest["iso_uke"]) & (norway["iso_aar"] < latest["iso_aar"])]
    median_same_week = same_week["fyllingsgrad"].median()

    st.write(
        "This app looks at how full Norway's hydropower reservoirs are. The data is weekly reservoir "
        "statistics from NVE (Norwegian Water Resources and Energy Directorate): for every week since "
        f"{df['dato_Id'].min():%Y}, it gives how much energy is stored in the reservoirs, both in TWh and "
        "as a share of the total capacity."
    )
    st.write(
        "Reservoirs follow the same cycle every year. They drain through the winter, when demand is high "
        "and rivers are frozen, reach their lowest point around April–May, and refill when the snow melts "
        "in late spring and summer."
    )

    st.subheader("Key numbers")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        f"Norway fill ratio, week {latest['iso_uke']} {latest['iso_aar']}",
        f"{latest['fyllingsgrad']:.1%}",
        f"{(latest['fyllingsgrad'] - median_same_week) * 100:+.1f} pp vs. median",
    )
    c2.metric("Total capacity", f"{latest['kapasitet_TWh']:.1f} TWh")
    c3.metric("Period", f"{df['dato_Id'].min():%Y}–{df['dato_Id'].max():%Y}")
    c4.metric("Rows", f"{len(df):,}", f"{df['area'].nunique()} areas, {norway['dato_Id'].nunique():,} weeks", delta_color="off")

    st.subheader("Areas")
    st.write(
        "Each week has one row per area. The same country is split up in two different ways, so the "
        "areas overlap:"
    )
    st.markdown(
        "- **NO 0** — Norway as a whole.\n"
        "- **EL 1–5** — the five electricity price areas (NO1–NO5). Together they make up all of Norway.\n"
        "- **VASS 1–3** — three regional areas. These also add up to all of Norway.\n\n"
        "Because of the overlap, rows from different area types should not be added together."
    )

    summary = df.groupby("area").agg(
        capacity_twh=("kapasitet_TWh", "first"),
        mean_fill_ratio=("fyllingsgrad", "mean"),
        min_fill_ratio=("fyllingsgrad", "min"),
        max_fill_ratio=("fyllingsgrad", "max"),
        latest_fill_ratio=("fyllingsgrad", "last"),
    )
    st.dataframe(
        summary,
        column_config={
            "capacity_twh": st.column_config.NumberColumn("Capacity (TWh)", format="%.1f"),
            "mean_fill_ratio": st.column_config.NumberColumn("Mean fill", format="percent"),
            "min_fill_ratio": st.column_config.NumberColumn("Lowest fill", format="percent"),
            "max_fill_ratio": st.column_config.NumberColumn("Highest fill", format="percent"),
            "latest_fill_ratio": st.column_config.NumberColumn("Latest fill", format="percent"),
        },
    )

    st.subheader("Columns")
    st.table(pd.DataFrame(
        [
            ("dato_Id", "date", "Date of the measurement (one per week)"),
            ("omrType / omrnr", "area_type / area_number", "Area type (NO, EL, VASS) and number"),
            ("iso_aar / iso_uke", "iso_year / iso_week", "ISO year and week number"),
            ("fyllingsgrad", "fill_ratio", "Share of capacity that is filled (0–1)"),
            ("kapasitet_TWh", "capacity_twh", "Total reservoir capacity in the area, in TWh"),
            ("fylling_TWh", "filling_twh", "Energy stored in the reservoirs, in TWh"),
            ("fyllingsgrad_forrige_uke", "fill_ratio_prev_week", "Fill ratio the week before"),
            ("endring_fyllingsgrad", "fill_ratio_change", "Change in fill ratio since last week"),
            ("neste_Publiseringsdato", "next_publish_date", "When the next week is published (blank for older rows)"),
        ],
        columns=["Original column", "Name in this app", "Meaning"],
    ).set_index("Original column"))

    st.caption("Use the sidebar to see the data table and plots.")


pg = st.navigation([
    st.Page(home, title="Home", default=True),
    st.Page("pages/1_Data_Table.py", title="Data Table"),
    st.Page("pages/2_Plot.py", title="Plot"),
    st.Page("pages/3_Coming_Soon.py", title="Coming Soon"),
])
pg.run()
