import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from utils.mongo_utils import get_db

# Daily ERA5 weather from Open-Meteo for the area chosen in the sidebar.
# The download is a hidden part of the app: a page asks for (area, year), and anything not
# already in MongoDB is downloaded and saved there, so each area and year is only paid for once,
# by the first visitor. The free API allows 10,000 calls per day (see the part 3 notebook for
# how a request is counted), so the app uses a few locations per area and counts its own calls.

ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"

# the random locations from the part 3 notebook: 1000 sampled for each region, with their EL and VASS area
LOCATIONS_FILE = Path(__file__).parent.parent / "Data" / "sample_locations.csv"

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


# the locations used for an area: a fixed random choice of up to MAX_LOCATIONS among the
# 1000 locations the notebook sampled for that area
def locations_for_area(area):
    locations = load_locations()
    if area == "NO 0":
        # all of Norway: the locations sampled for the five price areas cover the whole country
        locations = locations[locations["sampled_for"].str.startswith("EL")]
    else:
        locations = locations[locations["sampled_for"] == area]
    return locations.sample(n=min(MAX_LOCATIONS, len(locations)), random_state=320).sort_index()


# MongoDB filter for the stored documents of these locations. The coordinates are part of the
# filter, so a document from an older sample with the same point_id is not used by mistake.
def stored_filter(points, year):
    return {
        "year": year,
        "$or": [
            {"point_id": int(point_id), "lon": point["lon"], "lat": point["lat"]}
            for point_id, point in points.iterrows()
        ],
    }


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
        for doc in collection.find({**stored_filter(points, year), "end": str(end)}, {"point_id": 1})
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
    docs = get_db()["weather_daily"].find(stored_filter(points, year), {"_id": 0})
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


# The last `days` days of weather for an area, for the key numbers on the home page.
# ERA5 is about a week behind, so this uses Open-Meteo's forecast API, which also has the
# recent past (past_days). A month for a few locations costs 1 call each; cached for 6 hours.
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
RECENT_VARIABLES = ["temperature_2m_mean", "precipitation_sum", "snowfall_sum"]


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Loading recent weather from Open-Meteo...")
def recent_weather(area, days=30, n_locations=5):
    points = locations_for_area(area).head(n_locations)
    resp = requests.get(FORECAST_URL, timeout=30, params={
        "latitude": ",".join(str(lat) for lat in points["lat"]),
        "longitude": ",".join(str(lon) for lon in points["lon"]),
        "daily": ",".join(RECENT_VARIABLES),
        "past_days": days,
        "forecast_days": 0,  # only days that have happened
        "timezone": "Europe/Oslo",
    })
    resp.raise_for_status()
    add_calls(float(resp.headers.get("X-RateLimit-Cost", len(points))))
    results = resp.json()
    if isinstance(results, dict):
        results = [results]
    frames = [pd.DataFrame(r["daily"]) for r in results]
    # one value per day: the average over the locations
    daily = pd.concat(frames).groupby("time").mean()
    daily.index = pd.to_datetime(daily.index)
    return daily


# Daily ERA5 weather for an area over a short period, for colouring the map. A few locations per
# area are enough for an area average, and a period of a few weeks costs only a few calls per
# location, so this is downloaded directly instead of a whole year as on the Weather page.
# The past does not change, so the result is cached without a time limit.
@st.cache_data(show_spinner=False, max_entries=500)
def period_weather(area, start, end, n_locations=5):
    points = locations_for_area(area).head(n_locations)
    days = (end - start).days + 1
    estimate = max(days / 14 * len(DAILY_VARIABLES) / 10, 1) * len(points)
    if calls_used_today() + estimate > APP_DAILY_BUDGET:
        raise RuntimeError("The app's daily budget for weather downloads is used up. Try again tomorrow.")
    docs, cost = fetch_locations(points, start, end)
    add_calls(cost)
    frames = [pd.DataFrame(doc["daily"]) for doc in docs]
    daily = pd.concat(frames).groupby("time").mean()  # average over the locations
    daily.index = pd.to_datetime(daily.index)
    return daily


# Daily weather for a whole area and year as one average series, for the correlation page.
# A correlation over many years needs many years of weather, so this uses only 5 locations per area
# (about 130 calls per year instead of 520) and stores the area average in MongoDB, so each area
# and year is only downloaded once. The current year is downloaded again when it is a week behind.
AREA_LOCATIONS = 5


def area_daily_weather(area, year):
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), latest_era5_date())
    if end < start:
        return pd.DataFrame()
    collection = get_db()["weather_area_daily"]
    doc = collection.find_one({"area": area, "year": year, "n_locations": AREA_LOCATIONS})
    if doc is None or (doc["end"] != str(end) and date.fromisoformat(doc["end"]) < end - timedelta(days=6)):
        points = locations_for_area(area).head(AREA_LOCATIONS)
        cost = max(((end - start).days + 1) / 14 * len(DAILY_VARIABLES) / 10, 1) * len(points)
        if calls_used_today() + cost > APP_DAILY_BUDGET:
            raise RuntimeError("The app's daily budget for weather downloads is used up. Try again tomorrow.")
        try:
            docs, cost = fetch_locations(points, start, end)
        except requests.HTTPError as error:
            # several years in a row can pass the limit of 600 calls per minute: wait and try once more
            if error.response is None or error.response.status_code != 429 or "Minutely" not in error.response.text:
                raise
            with st.spinner("Open-Meteo allows 600 calls per minute. Waiting a minute before the next year..."):
                time.sleep(61)
            docs, cost = fetch_locations(points, start, end)
        add_calls(cost)
        daily = pd.concat(pd.DataFrame(d["daily"]) for d in docs).groupby("time").mean()
        doc = {"area": area, "year": year, "n_locations": AREA_LOCATIONS, "end": str(end),
               "daily": daily.reset_index().to_dict("list")}
        collection.replace_one({"area": area, "year": year, "n_locations": AREA_LOCATIONS}, doc, upsert=True)
    daily = pd.DataFrame(doc["daily"]).set_index("time")
    daily.index = pd.to_datetime(daily.index)
    return daily


# weather properties per week for the correlation and forecast pages: the ERA5 variable and how the
# daily values become one value per week (Monday-Sunday, dated on the Sunday like NVE)
WEEKLY_WEATHER = {
    "Precipitation (mm/week)": ("precipitation_sum", "sum"),
    "Rain (mm/week)": ("rain_sum", "sum"),
    "Snowfall (cm/week)": ("snowfall_sum", "sum"),
    "Mean temperature (°C)": ("temperature_2m_mean", "mean"),
    "Maximum temperature (°C)": ("temperature_2m_max", "mean"),
    "Minimum temperature (°C)": ("temperature_2m_min", "mean"),
    "Mean wind speed (m/s)": ("wind_speed_10m_mean", "mean"),
    "Solar radiation (MJ/m² per week)": ("shortwave_radiation_sum", "sum"),
    "Evapotranspiration (mm/week)": ("et0_fao_evapotranspiration", "sum"),
}


def to_weekly(daily, label):
    """One weather property per week, only for whole weeks."""
    variable, how = WEEKLY_WEATHER[label]
    weekly = daily[variable].resample("W-SUN")
    values = weekly.sum() if how == "sum" else weekly.mean()
    return values[weekly.count() == 7].rename(label)


def missing_area_years(area, years):
    """The years that area_daily_weather would have to download (about 130 calls each)."""
    stored = {doc["year"] for doc in get_db()["weather_area_daily"].find(
        {"area": area, "n_locations": AREA_LOCATIONS, "year": {"$in": list(years)}}, {"year": 1})}
    return [y for y in years if y not in stored]
