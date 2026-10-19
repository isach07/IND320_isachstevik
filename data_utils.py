import pandas as pd
import requests
import streamlit as st

# NVE's public reservoir statistics API (Magasinstatistikk). No key is needed.
NVE_URL = "https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData"

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

# the three ways the API splits up Norway, used by the radio buttons in the app
AREA_TYPES = {
    "EL": "Price areas (EL 1–5)",
    "NO": "Norway as a whole (NO 0)",
    "VASS": "Regional areas (VASS 1–3)",
}


# downloads all weeks for all areas from the NVE API.
# cached for 6 hours: NVE publishes new numbers once a week, so there is no need
# to download again on every click, but the app still picks up new weeks by itself.
@st.cache_data(ttl=6 * 60 * 60, show_spinner="Downloading reservoir data from NVE...")
def fetch_nve():
    resp = requests.get(NVE_URL, timeout=30)
    resp.raise_for_status()  # stop with a clear error if the API call fails
    return clean_data(pd.DataFrame(resp.json()))


# returns the cleaned reservoir data, optionally only for the years start_year to end_year.
# the NVE API has no date filter (it always returns every week since 1995), so the
# interval is applied right after the download. Each interval is cached on its own.
@st.cache_data(ttl=6 * 60 * 60)
def load_data(start_year=None, end_year=None):
    df = fetch_nve()
    if start_year is not None:
        df = df[df["iso_year"] >= start_year]
    if end_year is not None:
        df = df[df["iso_year"] <= end_year]
    return df


# cleans raw reservoir data with the original Norwegian columns from the NVE API.
# returns a data frame with English column names, sorted by area and date.
def clean_data(df):
    df = df.copy()
    df["dato_Id"] = pd.to_datetime(df["dato_Id"])  # turns the "dato_Id" column into a datetime column
    df["neste_Publiseringsdato"] = pd.to_datetime(
        # 0001-01-01 is a placeholder for "no date"; replace it with None, which becomes NaT
        df["neste_Publiseringsdato"].replace("0001-01-01T00:00:00", None)
    )
    df = df.rename(columns=COLUMN_NAMES)
    df["area"] = df["area_type"] + " " + df["area_number"].astype(str)  # e.g. "NO 0", "EL 1"
    return df.sort_values(["area", "date"]).reset_index(drop=True)


# returns the numeric columns that are measurements (not identifiers).
def numeric_columns(df):
    return df.select_dtypes("number").columns.drop(ID_COLS).tolist()