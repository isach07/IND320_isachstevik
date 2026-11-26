"""Short facts about each data source, shown in an "About the data" box on the Explore pages.

One place for the text, so the overview page and the analysis pages of a source say the same thing.
"""
import streamlit as st

SOURCES = {
    "reservoir": {
        "title": "Reservoirs (NVE Magasinstatistikk)",
        "rows": [
            ("What", "How full the hydropower reservoirs are (fill ratio), plus capacity and fill in TWh, "
                     "for Norway (NO), the price areas (EL 1–5) and the water areas (VASS 1–4)."),
            ("Data type", "Weekly time series, one value per ISO week (the week ending on Sunday). Starts in 1995."),
            ("How often new data comes", "Once a week, when NVE publishes the new week (usually Wednesday)."),
            ("How the app gets it", "Downloaded straight from the NVE API. Not stored in MongoDB: the whole "
                                    "history is small and the API is fast."),
            ("Caching", "Cached for 6 hours (`st.cache_data(ttl=6 h)`), so new weeks show up the same day "
                        "without downloading on every click."),
        ],
    },
    "weather": {
        "title": "Weather (Open-Meteo, ERA5)",
        "rows": [
            ("What", "Daily temperature, precipitation, rain, snowfall, wind, solar radiation and evaporation "
                     "for random locations in each area (sampled in the part 3 notebook)."),
            ("Data type", "Daily time series per location (ERA5 reanalysis, about 25 km grid). The pages show "
                          "the average over the area's locations, and weekly sums or means where it is compared "
                          "with the reservoirs."),
            ("How often new data comes", "Every day, about 5–7 days behind real time."),
            ("How the app gets it", "Downloaded from the Open-Meteo archive API the first time an area and year "
                                    "is needed, then stored in MongoDB (`weather_daily` per location, "
                                    "`weather_area_daily` per area). The next visit reads MongoDB with no API call."),
            ("Caching", "MongoDB reads are cached for 1 hour. API use is counted in MongoDB (`weather_usage`) "
                        "and stopped at the app's daily budget, so the free limit is never passed."),
        ],
    },
    "crossborder": {
        "title": "Cross-border flows (ENTSO-E)",
        "rows": [
            ("What", "Physical electricity flows between the Norwegian price areas and the neighbouring "
                     "countries, in both directions (into and out of Norway)."),
            ("Data type", "Hourly values from ENTSO-E, summed to daily totals in MWh per connection and direction. "
                          "From 2024."),
            ("How often new data comes", "ENTSO-E publishes every hour; the app's copy is updated when the "
                                         "notebook is run again."),
            ("How the app gets it", "Downloaded in the notebook with `entsoe-py` (needs an API key), stored in "
                                    "Cassandra, summed to days with Spark and saved in MongoDB "
                                    "(`crossborder_daily`). The app only reads MongoDB."),
            ("Caching", "The MongoDB read is cached for 1 hour."),
        ],
    },
}


def show_source_info(source, expanded=False):
    """An expander with the facts about one data source."""
    info = SOURCES[source]
    with st.expander(f"About the data: {info['title']}", expanded=expanded, icon=":material/info:"):
        st.markdown("\n".join(f"- **{label}:** {text}" for label, text in info["rows"]))
