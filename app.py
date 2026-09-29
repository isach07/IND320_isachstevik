import streamlit as st

st.set_page_config(page_title="IND320 Reservoirs", layout="wide")

# this bulids the navigation sidebar with links to the other pages.
pg = st.navigation([
    st.Page("pages/0_Home.py", title="Home", default=True),
    st.Page("pages/1_Data_Table.py", title="Data Table"),
    st.Page("pages/2_Plot.py", title="Plot"),
    st.Page("pages/3_Coming_Soon.py", title="Coming Soon"),
])
pg.run()
