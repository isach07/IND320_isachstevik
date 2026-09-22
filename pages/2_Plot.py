import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="Plot", layout="wide")

@st.cache_data
def load_data():
    df = pd.read_csv("data/reservoirs.csv", parse_dates=["dato_Id"])
    return df.rename(columns={"dato_Id": "date"})

df = load_data()
st.title("Reservoir Data Plot")

numeric_cols = df.select_dtypes("number").columns.tolist()
choice = st.selectbox("Choose column", ["All columns"] + numeric_cols)

months = sorted(df["date"].dt.to_period("M").unique().astype(str))
month_range = st.select_slider("Select month range", options=months, value=months[0])

fig, ax = plt.subplots()
subset = df[df["date"].dt.to_period("M").astype(str) <= month_range]
if choice == "All columns":
    for c in numeric_cols:
        ax.plot(subset["date"], subset[c], label=c)
    ax.legend()
else:
    ax.plot(subset["date"], subset[choice])
ax.set_xlabel("Date")
ax.set_ylabel("Value")
ax.set_title(f"Reservoir data — {choice}")
st.pyplot(fig)