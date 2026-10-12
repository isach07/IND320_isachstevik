import streamlit as st
import pandas as pd
from data_utils import load_data, numeric_columns
import matplotlib.pyplot as plt

# settning up the page.
st.set_page_config(page_title="Plot", layout="wide")

df = load_data()
st.title("Reservoir Data Plot")

# each date has one row per area, so plot one area at a time
areas = sorted(df["area"].unique(), key=lambda a: a != "NO 0")
area = st.selectbox("Choose area", areas, format_func=lambda a: "Norway (total)" if a == "NO 0" else a)
df = df[df["area"] == area]

numeric_cols = numeric_columns(df)
choice = st.selectbox("Choose column", ["All columns"] + numeric_cols)

months = sorted(df["date"].dt.to_period("M").unique())
# slider with a start and end point to select the months to show, set to the first month by default.
start_month, end_month = st.select_slider(
    "Select month range", options=months, value=(months[0], months[0]), format_func=str
)

fig, ax = plt.subplots()
month = df["date"].dt.to_period("M")
subset = df[(month >= start_month) & (month <= end_month)]
if choice == "All columns":
    # the columns have very different scales, so normalize each to 0-1
    # capacity_twh is constant, so its range is 0; use 1 instead to avoid dividing by zero
    value_range = (subset[numeric_cols].max() - subset[numeric_cols].min()).replace(0, 1)
    normalized = (subset[numeric_cols] - subset[numeric_cols].min()) / value_range
    for c in numeric_cols:
        ax.plot(subset["date"], normalized[c], label=c)
    ax.legend()
    ax.set_ylabel("Normalized value (0-1)")
else:
    ax.plot(subset["date"], subset[choice])
    ax.set_ylabel(choice)
ax.set_xlabel("Date")
ax.set_title(f"Reservoir data — {area} — {choice} ({start_month} to {end_month})")
st.pyplot(fig)