import streamlit as st
import pandas as pd
from data_utils import load_data, numeric_columns
# this code is generating one small table.
# each row is a measureemnet column from the data.


# page config must be set befor any other stremlit commands.
st.set_page_config(page_title="Data Table", layout="wide")

# load the data (cached in data_utils, so it is only read once for all pages).
df = load_data()
st.title("Data Table")

# each date has one row per area, so use the Norway total
df = df[(df["area_type"] == "NO") & (df["area_number"] == 0)]

numeric_cols = numeric_columns(df)
first_month = df[df["date"] < df["date"].min() + pd.DateOffset(months=1)]

# create a table with the first month trend for each numeric column
table = pd.DataFrame({
    "column": numeric_cols,
    "first_month_trend": [first_month[c].tolist() for c in numeric_cols],
})

# display the table with a line chart for the first month trend
st.dataframe(
    table,
    column_config={
        "first_month_trend": st.column_config.LineChartColumn("First month"),
    },
    hide_index=True,
)