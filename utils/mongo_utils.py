import pandas as pd
import streamlit as st
from pymongo import MongoClient

# The MongoDB connection string is read from Streamlit secrets:
# - locally from .streamlit/secrets.toml (gitignored, so it is never pushed to GitHub)
# - on streamlit.app from the "Secrets" field in the app settings


# one MongoDB client for the whole app; cache_resource keeps the connection open
# between reruns instead of reconnecting on every click.
@st.cache_resource
def get_db():
    client = MongoClient(st.secrets["mongo"]["uri"])
    return client["ind320"]


# loads the daily cross-border flows that the notebook prepared with Spark.
# cached for one hour, so MongoDB is only asked again if the data might have changed.
@st.cache_data(ttl=60 * 60, show_spinner="Loading cross-border data from MongoDB..:-)")
def load_crossborder():
    # {"_id": 0} leaves out MongoDB's internal id, which the app does not need
    docs = list(get_db()["crossborder_daily"].find({}, {"_id": 0}))
    df = pd.DataFrame(docs)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["connection", "direction", "date"]).reset_index(drop=True)

# daily import, export and net export (GWh) for an area: a price area (EL) uses its own connections
# abroad, Norway and the water areas use all of them (water areas have no connections of their own).
# A few missing days are filled by drawing a straight line, so STL and the spectrogram get a regular series.
def crossborder_for_area(df, area):
    if area.startswith("EL"):
        df = df[df["connection"].str.startswith(f"NO_{area[-1]}-")]
    if df.empty:
        return pd.DataFrame()
    daily = df.pivot_table(index="date", columns="direction", values="flow_mwh", aggfunc="sum") / 1000
    daily = daily.reindex(columns=["into Norway", "out of Norway"], fill_value=0)
    daily = daily.rename(columns={"into Norway": "import_gwh", "out of Norway": "export_gwh"})
    daily["net_export_gwh"] = daily["export_gwh"] - daily["import_gwh"]
    return daily.asfreq("D").interpolate(limit=3).dropna()
