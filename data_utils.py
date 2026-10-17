from pathlib import Path

import streamlit as st
import pandas as pd

# path to the CSV, relative to this file so it works from both the app and the notebooks.
DATA_FILE = Path(__file__).parent / "data" / "reservoirs.csv"

# the original Norwegian column names and the English names used in the app.
COLUMN_NAMES = {
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
}

# area_number, iso_year and iso_week are identifiers, not measurements
ID_COLS = ["area_number", "iso_year", "iso_week"]


# reads the CSV file once and caches it, so every page shares the same data.
# returns a data frame with English column names, sorted by area and date.
@st.cache_data
def load_data():
    return clean_data(pd.read_csv(DATA_FILE))


# cleans raw reservoir data with the original Norwegian columns, from the CSV or the NVE API.
# returns a data frame with English column names, sorted by area and date.
def clean_data(df):
    df = df.copy()
    df["dato_Id"] = pd.to_datetime(df["dato_Id"]) # turns the "dato_Id" column into a datetime column
    df["neste_Publiseringsdato"] = pd.to_datetime(
        df["neste_Publiseringsdato"].replace("0001-01-01T00:00:00", None) # replace the invalid date with None, which will be converted to NaT
    )
    df = df.rename(columns=COLUMN_NAMES)
    df["area"] = df["area_type"] + " " + df["area_number"].astype(str) # e.g. "NO 0", "EL 1"
    return df.sort_values(["area", "date"])


# returns the numeric columns that are measurements (not identifiers).
def numeric_columns(df):
    return df.select_dtypes("number").columns.drop(ID_COLS).tolist()
