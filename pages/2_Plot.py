import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="Plot", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv("data/reservoirs.csv", parse_dates=["dato_Id"])
    df["neste_Publiseringsdato"] = pd.to_datetime(
        df["neste_Publiseringsdato"].replace("0001-01-01T00:00:00", None)
    )
    df = df.rename(columns={
        "dato_Id": "date",
        "omrType": "area_type",
        "omrnr": "area_number",
        "iso_aar": "iso_year",
        "iso_uke": "iso_week",
        "fyllingsgrad": "fill_ratio",
        "kapasitet_TWh": "capacity_twh",
        "fylling_TWh": "filling_twh",
        "neste_Publiseringsdato": "next_publish_date",
        "fyllingsgrad_forrige_uke": "fill_ratio_prev_week",
        "endring_fyllingsgrad": "fill_ratio_change",
    })
    df["area"] = df["area_type"] + " " + df["area_number"].astype(str)
    return df.sort_values("date")

df = load_data()
st.title("Reservoir Data Plot")

# each date has one row per area, so plot one area at a time
# Norway total first, then the other areas in alphabetical order
areas = sorted(df["area"].unique(), key=lambda a: (a != "NO 0", a))
area = st.selectbox("Choose area", areas, format_func=lambda a: "Norway (total)" if a == "NO 0" else a)
df = df[df["area"] == area]

# area_number, iso_year and iso_week are identifiers, not measurements
numeric_cols = df.select_dtypes("number").columns.drop(["area_number", "iso_year", "iso_week"]).tolist()
choice = st.selectbox("Choose column", ["All columns"] + numeric_cols)

months = sorted(df["date"].dt.to_period("M").unique().astype(str))
start_month, end_month = st.select_slider(
    "Select month range", options=months, value=(months[0], months[-1])
)

fig, ax = plt.subplots(figsize=(12, 5))
month = df["date"].dt.to_period("M").astype(str)
subset = df[(month >= start_month) & (month <= end_month)]
if choice == "All columns":
    # the columns have very different scales, so normalize each to 0-1
    # capacity_twh is constant, so its range is 0; use 1 instead to avoid dividing by zero
    value_range = (subset[numeric_cols].max() - subset[numeric_cols].min()).replace(0, 1)
    normalized = (subset[numeric_cols] - subset[numeric_cols].min()) / value_range
    for c in numeric_cols:
        ax.plot(subset["date"], normalized[c], label=c, linewidth=0.8)
    ax.set_ylabel("Normalized value (0-1)")
    ax.legend(loc="upper left", bbox_to_anchor=(1, 1))
else:
    ax.plot(subset["date"], subset[choice], linewidth=0.8)
    ax.set_ylabel(choice)
ax.set_xlabel("Date")
ax.set_title(f"Reservoir data — {area} — {choice} ({start_month} to {end_month})")
plt.tight_layout()
st.pyplot(fig)
