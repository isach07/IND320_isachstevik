import streamlit as st
 
st.set_page_config(page_title="IND320 Reservoirs", layout="wide")
 
# this builds the navigation sidebar with links to the other pages.
pg = st.navigation([
    st.Page("pages/0_Home.py", title="Home", default=True),
    st.Page("pages/1_Reservoirs.py", title="Reservoirs"),  # replaces "Data Table" and "Plot" from part 1
    st.Page("pages/2_Cross_Border.py", title="Cross-border flows"),
    st.Page("pages/3_Coming_Soon.py", title="Coming Soon"),
])
pg.run()
 