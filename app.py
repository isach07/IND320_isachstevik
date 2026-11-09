import streamlit as st

from data_utils import AREAS

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

# this builds the navigation sidebar with links to the other pages.
pg = st.navigation([
    st.Page("app_pages/0_Home.py", title="Home", default=True),
    st.Page("app_pages/1_Reservoirs.py", title="Reservoirs"),  # replaces "Data Table" and "Plot" from part 1
    st.Page("app_pages/2_Cross_Border.py", title="Cross-border flows"),
    st.Page("app_pages/4_Weather.py", title="Weather"),
    st.Page("app_pages/5_STL_Spectrogram.py", title="STL and spectrogram"),
    st.Page("app_pages/6_Outliers.py", title="Outliers and anomalies"),
])
pg.run()
