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
    df = df.rename(columns={"dato_Id": "date"})
    df["area"] = df["omrType"] + " " + df["omrnr"].astype(str)
    return df.sort_values("date")

df = load_data()
st.title("Reservoir Data Plot")

# each date has one row per area, so plot one area at a time
areas = sorted(df["area"].unique(), key=lambda a: a != "NO 0")
area = st.selectbox("Choose area", areas, format_func=lambda a: "Norway (total)" if a == "NO 0" else a)
df = df[df["area"] == area]

# omrnr, iso_aar and iso_uke are identifiers, not measurements
numeric_cols = df.select_dtypes("number").columns.drop(["omrnr", "iso_aar", "iso_uke"]).tolist()
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
ax.set_title(f"Reservoir data — {area} — {choice}")
st.pyplot(fig)