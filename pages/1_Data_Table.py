import streamlit as st
import pandas as pd

st.set_page_config(page_title="Data Table", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv("data/reservoirs.csv", parse_dates=["dato_Id"])
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
    return df

df = load_data()
st.title("Data Table")

numeric_cols = df.select_dtypes("number").columns
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