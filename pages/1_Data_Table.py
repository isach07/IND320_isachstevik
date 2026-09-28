import streamlit as st
import pandas as pd

st.set_page_config(page_title="Data Table", layout="wide")

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
    return df.sort_values("date")

df = load_data()
st.title("Data Table")

# each date has one row per area, so use the Norway total
df = df[(df["area_type"] == "NO") & (df["area_number"] == 0)]

# area_number, iso_year and iso_week are identifiers, not measurements
numeric_cols = df.select_dtypes("number").columns.drop(["area_number", "iso_year", "iso_week"])
first_month = df[df["date"] < df["date"].min() + pd.DateOffset(months=1)]

table = pd.DataFrame({
    "column": numeric_cols,
    "first_month_trend": [first_month[c].tolist() for c in numeric_cols],
})

st.dataframe(
    table,
    column_config={
        "first_month_trend": st.column_config.LineChartColumn("First month"),
    },
    hide_index=True,
)