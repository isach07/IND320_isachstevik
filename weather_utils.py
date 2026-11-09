import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from mongo_utils import get_db

# Daily ERA5 weather from Open-Meteo for the area chosen in the sidebar.
# The download is a hidden part of the app: a page asks for (area, year), and anything not
# already in MongoDB is downloaded and saved there, so each area and year is only paid for once,
# by the first visitor. The free API allows 10,000 calls per day (see the part 3 notebook for
# how a request is counted), so the app uses a few locations per area and counts its own calls.

ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"

# the 1000 random locations from the part 3 notebook, with their EL and VASS area
LOCATIONS_FILE = Path(__file__).parent / "Data" / "sample_locations.csv"

# one year for one location with 10 variables costs about 26 calls, so 20 locations cost
# about 520. That stays under the limit of 600 calls per minute without any waiting.
MAX_LOCATIONS = 20
APP_DAILY_BUDGET = 5000  # the app's share of the 10,000 calls per day
ERA5_DELAY_DAYS = 7      # ERA5 is about 5 days behind

# the same 10 variables as in the notebook (each extra one adds 10% to the cost)
DAILY_VARIABLES = [
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "precipitation_hours",
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "wind_speed_10m_mean",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
]


@st.cache_data
def load_locations():
    return pd.read_csv(LOCATIONS_FILE, index_col="point_id")


# the locations used for an area: a fixed random choice of up to MAX_LOCATIONS
def locations_for_area(area):
    locations = load_locations()
    if area.startswith("EL"):
        locations = locations[locations["el_area"] == area]
    elif area.startswith("VASS"):
        locations = locations[locations["vass_area"] == area]
    # "NO 0" uses all of Norway
    return locations.sample(n=min(MAX_LOCATIONS, len(locations)), random_state=320).sort_index()


# the last date ERA5 has data for
def latest_era5_date():
    return date.today() - timedelta(days=ERA5_DELAY_DAYS)


# year selector shared by the pages that show weather. The choice is kept in session_state under
# its own key (not the widget's), because Streamlit forgets a widget's value when you leave its page.
def weather_year_selector():
    years = list(range(latest_era5_date().year, 1999, -1))
    default = st.session_state.get("weather_year", years[1])  # last complete year
    year = st.selectbox("Year", years, index=years.index(default),
                        help="Shared by the weather pages.")
    st.session_state["weather_year"] = year
    return year


def calls_used_today():
    today = str(datetime.now(timezone.utc).date())
    doc = get_db()["weather_usage"].find_one({"_id": today})
    return doc["calls"] if doc else 0.0


def add_calls(cost):
    today = str(datetime.now(timezone.utc).date())
    get_db()["weather_usage"].update_one({"_id": today}, {"$inc": {"calls": cost}}, upsert=True)


# downloads one year for several locations in one request, returns one MongoDB document per
# location and the total cost in calls. The cost is the same as one request per location, but
# one request answers about as fast as a single location, so it is much quicker.
def fetch_locations(points, start, end, timeout=60):
    resp = requests.get(ERA5_URL, timeout=timeout, params={
        "latitude": ",".join(str(lat) for lat in points["lat"]),
        "longitude": ",".join(str(lon) for lon in points["lon"]),
        "start_date": start,
        "end_date": end,
        "daily": ",".join(DAILY_VARIABLES),
        "models": "era5",
        "timezone": "Europe/Oslo",
        "wind_speed_unit": "ms",
    })
    resp.raise_for_status()
    results = resp.json()
    if isinstance(results, dict):  # a single location comes back as one object, not a list
        results = [results]
    docs = [
        {
            "point_id": int(point_id),
            "year": start.year,
            "end": str(end),  # the current year is only partly downloaded, so the end date is kept
            "lon": point["lon"],
            "lat": point["lat"],
            "elevation": result["elevation"],
            "daily": result["daily"],  # one list per variable, plus "time"
        }
        for (point_id, point), result in zip(points.iterrows(), results)  # same order as requested
    ]
    return docs, float(resp.headers.get("X-RateLimit-Cost", 0))


# downloads one location and year, returns the MongoDB document and the cost in calls
def fetch_location(point_id, lon, lat, start, end):
    point = pd.DataFrame({"lon": [lon], "lat": [lat]}, index=[point_id])
    docs, cost = fetch_locations(point, start, end, timeout=20)
    return docs[0], cost


# Open-Meteo sometimes does not answer a request; one more try after a few seconds usually works
def fetch_with_retry(point_id, lon, lat, start, end):
    try:
        return fetch_location(point_id, lon, lat, start, end)
    except (requests.Timeout, requests.ConnectionError):
        time.sleep(5)
        return fetch_location(point_id, lon, lat, start, end)


# makes sure MongoDB has the weather for an area and year, downloading what is missing.
# returns a short status for the page to show.
def ensure_weather(area, year):
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), latest_era5_date())
    if end < start:
        return {"downloaded": 0, "stored": 0, "missing": 0, "message": f"No ERA5 data for {year} yet."}

    points = locations_for_area(area)
    collection = get_db()["weather_daily"]
    stored = {
        doc["point_id"]
        for doc in collection.find(
            {"year": year, "end": str(end), "point_id": {"$in": [int(i) for i in points.index]}},
            {"point_id": 1},
        )
    }
    todo = points[~points.index.isin(stored)]
    status = {"downloaded": 0, "stored": len(stored), "missing": 0, "message": None}
    if todo.empty:
        return status

    days = (end - start).days + 1
    cost_each = max(days / 14 * len(DAILY_VARIABLES) / 10, 1)

    # fast way: everything missing in one request (at most 20 locations, about 520 calls,
    # which stays under the limit of 600 calls per minute)
    if calls_used_today() + cost_each * len(todo) <= APP_DAILY_BUDGET:
        try:
            with st.spinner(f"Downloading weather for {area}, {year} ({len(todo)} locations)..."):
                docs, cost = fetch_locations(todo, start, end)
            for doc in docs:
                # replace any older, shorter version of the current year
                collection.replace_one({"point_id": doc["point_id"], "year": year}, doc, upsert=True)
            add_calls(cost)
            status["downloaded"] = len(docs)
            read_weather.clear()  # new data is in MongoDB
            return status
        except requests.RequestException:
            pass  # fall back to one location at a time below

    # slow way: one location at a time, skipping locations that fail
    progress = st.progress(0.0, text=f"Downloading weather for {area}, {year} ({len(todo)} locations)...")
    failures_in_a_row = 0
    for i, (point_id, point) in enumerate(todo.iterrows()):
        if calls_used_today() + cost_each > APP_DAILY_BUDGET:
            status["message"] = "The app's daily budget for weather downloads is used up. Try again tomorrow."
            break
        try:
            doc, cost = fetch_with_retry(point_id, point["lon"], point["lat"], start, end)
            failures_in_a_row = 0
        except requests.RequestException as error:
            # skip this location and go on; give up only if the API seems to be down
            failures_in_a_row += 1
            status["message"] = (
                f"Open-Meteo did not answer ({error.__class__.__name__}), so some locations are missing. "
                "Reload the page later to download the rest."
            )
            if failures_in_a_row == 3:
                break
            continue
        # replace any older, shorter version of the current year
        collection.replace_one({"point_id": doc["point_id"], "year": year}, doc, upsert=True)
        add_calls(cost)
        status["downloaded"] += 1
        progress.progress((i + 1) / len(todo), text=f"Downloading weather for {area}, {year}: {i + 1} of {len(todo)}")
    progress.empty()
    status["missing"] = len(todo) - status["downloaded"]
    read_weather.clear()  # new data is in MongoDB
    return status


# reads the stored weather for an area and year as one row per location and day
@st.cache_data(ttl=60 * 60, show_spinner="Loading weather from MongoDB...")
def read_weather(area, year):
    points = locations_for_area(area)
    docs = get_db()["weather_daily"].find(
        {"year": year, "point_id": {"$in": [int(i) for i in points.index]}}, {"_id": 0}
    )
    frames = []
    for doc in docs:
        daily = pd.DataFrame(doc["daily"]).rename(columns={"time": "date"})
        daily["point_id"] = doc["point_id"]
        frames.append(daily)
    if not frames:
        return pd.DataFrame()
    weather = pd.concat(frames, ignore_index=True)
    weather["date"] = pd.to_datetime(weather["date"])
    return weather
