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