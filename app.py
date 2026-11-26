import streamlit as st

from utils.data_utils import AREAS

st.set_page_config(page_title="IND320 Reservoirs", layout="wide")

# The area selector is global: it lives in the sidebar on every page, and the pages read the
# choice from st.session_state["area"]. Because the widget is created here (in app.py, which
# runs before every page), the choice is kept when the user moves between pages.
with st.sidebar:
    st.selectbox(
        "Area",
        options=list(AREAS),
        format_func=lambda a: AREAS[a],
        index=list(AREAS).index("EL 3"),
        key="area",
        help="Used by the reservoir, weather and analysis pages.",
    )

# this builds the navigation sidebar. On top, without a header: the front page and the two main
# tools (the map and the forecast). Below, "Explore the data" has one page per data source. Each of
# them has the same tabs (explore the raw data, STL and spectrogram, outliers and anomalies), so
# the sources can be compared in the same way.
pg = st.navigation({
    "": [
        st.Page("app_pages/0_Home.py", title="Home", icon=":material/home:", default=True),
        st.Page("app_pages/7_Map.py", title="Map", icon=":material/map:"),
        st.Page("app_pages/9_Forecast.py", title="Forecast", icon=":material/trending_up:"),
    ],
    "Explore the data": [
        st.Page("app_pages/1_Reservoirs.py", title="Reservoirs", icon=":material/water_drop:"),
        st.Page("app_pages/4_Weather.py", title="Weather", icon=":material/partly_cloudy_day:"),
        st.Page("app_pages/2_Cross_Border.py", title="Cross-border flows", icon=":material/swap_horiz:"),
    ],
})
pg.run()
