"""Forecasts of the reservoir filling (Magasinstatistikk) for one region, with River.

The model is River's SNARIMAX, a seasonal ARIMA with optional exogenous variables (SARIMAX).
It learns online, one week at a time.

Time resolution: weekly, the resolution of Magasinstatistikk itself (one value per ISO week,
dated on Sunday). Daily data sources are averaged or summed per week. The part 4 notebook
compares this with a daily resolution.

Data sources that can be selected as inputs (exogenous variables):
- "weather": weekly precipitation, snowfall and mean temperature for the region (ERA5 from
  Open-Meteo, averaged over a few of the sampled locations from part 3)
- "exchange_rates": weekly EUR/NOK from Norges Bank
Future values of the sources are unknown when forecasting, so the forecast uses the normal value
for that week of the year (weather) or the last known value (exchange rate).

The module has no Streamlit code, so it can be used both in the notebook and in the app.
"""

import functools
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from river import linear_model, optim, preprocessing, time_series

ROOT = Path(__file__).parent.parent   # the project folder
LOCATIONS_FILE = ROOT / "Data" / "sample_locations.csv"
WEATHER_CACHE = ROOT / "No_sync" / "forecast_weather"   # gitignored

NVE_URL = "https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData"
NB_URL = "https://data.norges-bank.no/api/data/EXR"
ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"

SOURCES = ("weather", "exchange_rates")
SOURCE_COLUMNS = {"weather": ["precipitation", "snowfall", "temperature"], "exchange_rates": ["eur_nok"]}
WEATHER_VARIABLES = ["precipitation_sum", "snowfall_sum", "temperature_2m_mean"]
WEATHER_LOCATIONS = 5         # locations per region for the weather, to save API calls
WEEKS_PER_YEAR = 52

# The best settings from the tests in the part 4 notebook; used as defaults in Streamlit
DEFAULTS = {
    "model_params": {"p": 1, "d": 1, "q": 0, "sp": 0, "sd": 1, "sq": 1, "learning_rate": 0.003},
    "history_years": 20,
    "horizon_weeks": 13,
    "sources": (),
}


# ---------------------------------------------------------------------------------------------
# Data sources, all at weekly resolution: weeks Monday-Sunday, dated on the Sunday like NVE
# ---------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _nve_all():
    """Every week for every area from Magasinstatistikk (one request, cached in memory)."""
    df = pd.DataFrame(requests.get(NVE_URL, timeout=60).json())
    df["date"] = pd.to_datetime(df["dato_Id"])
    df["area"] = df["omrType"] + " " + df["omrnr"].astype(str)
    return df[["date", "area", "fyllingsgrad"]]


def load_filling(area):
    """Weekly degree of filling for one area, in percent, dated on Sunday."""
    df = _nve_all()
    filling = df[df["area"] == area].set_index("date")["fyllingsgrad"].sort_index() * 100
    if filling.empty:
        raise ValueError(f"Unknown area: {area}")
    filling.name = "filling"
    return filling.asfreq("W-SUN")   # every Sunday, so missing weeks show up as NaN


@functools.lru_cache(maxsize=1)
def _eur_daily(start="1999-01-01"):
    """Daily EUR/NOK on business days from Norges Bank."""
    resp = requests.get(f"{NB_URL}/B.EUR.NOK.SP", timeout=60,
                        params={"format": "sdmx-json", "startPeriod": start, "locale": "en"})
    resp.raise_for_status()
    data = resp.json()["data"]
    dates = [v["id"] for v in data["structure"]["dimensions"]["observation"][0]["values"]]
    observations = next(iter(data["dataSets"][0]["series"].values()))["observations"]
    rates = pd.Series({dates[int(i)]: float(v[0]) for i, v in observations.items()})
    rates.index = pd.to_datetime(rates.index)
    return rates.sort_index()


def load_exchange_rates():
    """Weekly mean EUR/NOK, with weekends and holidays filled with the last known rate."""
    daily = _eur_daily()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D")).ffill()
    weekly = daily.resample("W-SUN").mean()
    weekly.name = "eur_nok"
    return weekly


def weather_locations(area, n=WEATHER_LOCATIONS):
    """A fixed random choice of n of the locations sampled for the area in part 3."""
    locations = pd.read_csv(LOCATIONS_FILE, index_col="point_id")
    if area == "NO 0":
        locations = locations[locations["sampled_for"].str.startswith("EL")]
    else:
        locations = locations[locations["sampled_for"] == area]
    return locations.sample(n=min(n, len(locations)), random_state=320).sort_index()


def weather_cost(n_locations, start, end):
    """Open-Meteo cost in API calls of one request (see the part 3 notebook)."""
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    return n_locations * max(days / 14 * len(WEATHER_VARIABLES) / 10, 1)


def load_weather(area, start, end, cache_dir=WEATHER_CACHE, max_calls=1500):
    """Weekly weather for the area: precipitation and snowfall summed per week, temperature
    averaged, all averaged over the chosen locations. Downloaded once and saved to cache_dir.
    """
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    name = area.replace(" ", "_")
    path = Path(cache_dir) / f"{name}_{start}_{end}.parquet"

    # use a saved download if it covers the whole period
    for saved in Path(cache_dir).glob(f"{name}_*.parquet"):
        saved_start, saved_end = (pd.Timestamp(s).date() for s in saved.stem.split("_")[-2:])
        if saved_start <= start and end <= saved_end:
            return pd.read_parquet(saved).loc[pd.Timestamp(start):pd.Timestamp(end)]

    points = weather_locations(area)
    cost = weather_cost(len(points), start, end)
    if cost > max_calls:
        raise ValueError(f"The weather download would cost {cost:.0f} API calls (limit {max_calls})")

    # One request per location, spread out so no minute uses more than 500 calls: a single
    # request costing more than the limit of 600 calls per minute is always refused.
    cost_each = cost / len(points)
    results, sent = [], []   # sent: (time, cost) of the requests in the last minute
    for _, point in points.iterrows():
        sent = [(t, c) for t, c in sent if time.time() - t < 60]
        if sent and sum(c for _, c in sent) + cost_each > 500:
            time.sleep(61 - (time.time() - sent[0][0]))
        params = {
            "latitude": point["lat"], "longitude": point["lon"],
            "start_date": str(start), "end_date": str(end),
            "daily": ",".join(WEATHER_VARIABLES),
            "models": "era5", "timezone": "Europe/Oslo",   # Norwegian days, as in part 3
        }
        for attempt in range(6):   # wait and try again if the hourly or minute limit is reached
            resp = requests.get(ERA5_URL, params=params, timeout=120)
            if resp.status_code != 429 or "daily" in resp.text.lower():
                break
            time.sleep(120)
        resp.raise_for_status()
        sent.append((time.time(), cost_each))
        results.append(resp.json())

    # mean over the locations per day, then per week
    daily = sum(pd.DataFrame(r["daily"]).set_index("time")[WEATHER_VARIABLES] for r in results) / len(results)
    daily.index = pd.to_datetime(daily.index)
    weekly = pd.DataFrame({
        "precipitation": daily["precipitation_sum"].resample("W-SUN").sum(),
        "snowfall": daily["snowfall_sum"].resample("W-SUN").sum(),
        "temperature": daily["temperature_2m_mean"].resample("W-SUN").mean(),
    })
    weekly = weekly[weekly.index <= pd.Timestamp(end)]   # drop a week that is cut by the end date
    path.parent.mkdir(parents=True, exist_ok=True)
    weekly.to_parquet(path)
    return weekly


def load_data(area, sources=(), start="1995-01-01", end=None, cache_dir=WEATHER_CACHE):
    """One weekly table for the area: the filling (percent) plus one column per source variable."""
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise ValueError(f"Unknown data sources: {unknown}. Choose from {SOURCES}")
    data = load_filling(area).to_frame()
    end = pd.Timestamp(end) if end is not None else data.index.max()
    data = data.loc[pd.Timestamp(start):end]
    if "exchange_rates" in sources:
        data = data.join(load_exchange_rates())
    if "weather" in sources:
        # whole weeks only: from the Monday of the first week to the last Sunday
        weather = load_weather(area, data.index.min() - pd.Timedelta(days=6), data.index.max(), cache_dir)
        data = data.join(weather)
    return data


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------

def _future_exog(data, columns, dates):
    """Values of the sources for future weeks: the normal value for that week of the year
    (weather) or the last known value (exchange rate)."""
    future = pd.DataFrame(index=dates)
    week = data.index.isocalendar().week.clip(upper=52)
    for col in columns:
        if col == "eur_nok":
            future[col] = data[col].dropna().iloc[-1]
        else:
            normal = data[col].groupby(week.values).mean()
            future[col] = normal.reindex(dates.isocalendar().week.clip(upper=52).values).values
    return future


MODEL_PARAMS = ("p", "d", "q", "sp", "sd", "sq", "learning_rate")
# For the confidence intervals: how fast the quantile models' intercept learns (the intercept is what
# moves the model to the lower or upper quantile), and how the one-week interval grows with the
# number of weeks ahead (h ** 0.75). Both chosen by testing coverage in the part 4 notebook.
QUANTILE_INTERCEPT_LR = 0.1
INTERVAL_GROWTH = 0.75


def _make_sarimax(params, alpha=None):
    """SARIMAX (p,d,q)(sp,sd,sq) with a seasonal period of 52 weeks. River fits it with an online
    linear regression (SGD). With alpha, the regression uses quantile loss, so the model predicts
    that quantile (e.g. alpha=0.05: a value the filling is below only 5 % of the time) instead of
    the mean."""
    unknown = set(params) - set(MODEL_PARAMS)
    if unknown:
        raise ValueError(f"Unknown model parameters: {unknown}. Choose from {MODEL_PARAMS}")
    p = {**DEFAULTS["model_params"], **params}
    if alpha is None:
        regression = linear_model.LinearRegression(optimizer=optim.SGD(p["learning_rate"]))
    else:
        regression = linear_model.LinearRegression(optimizer=optim.SGD(p["learning_rate"]),
                                                   loss=optim.losses.Quantile(alpha=alpha),
                                                   intercept_lr=QUANTILE_INTERCEPT_LR)
    return time_series.SNARIMAX(p=p["p"], d=p["d"], q=p["q"], m=WEEKS_PER_YEAR,
                                sp=p["sp"], sd=p["sd"], sq=p["sq"],
                                regressor=preprocessing.StandardScaler() | regression)


def _learn(models, history, exog_cols):
    """All models learn the same weeks, one at a time (online learning)."""
    for date, row in history.iterrows():
        x = {c: row[c] for c in exog_cols} if exog_cols else None
        for model in models:
            model.learn_one(row["filling"], x)


def _future_xs(future_exog, exog_cols):
    return [{c: row[c] for c in exog_cols} for _, row in future_exog.iterrows()] if exog_cols else None


def _fit_forecast(history, exog_cols, future_exog, horizon, params):
    """The SARIMAX forecast (the mean) for the coming weeks, with the data sources as exogenous variables."""
    model = _make_sarimax(params)
    _learn([model], history, exog_cols)
    return np.clip(model.forecast(horizon, xs=_future_xs(future_exog, exog_cols)), 0, 100)   # the filling is 0-100 %


def forecast_filling(area="EL 3", model_params=None,
                     history_years=DEFAULTS["history_years"], horizon_weeks=DEFAULTS["horizon_weeks"],
                     sources=DEFAULTS["sources"], end=None, data=None):
    """Forecast the weekly degree of filling (percent) for one area.

    area: Magasinstatistikk area, e.g. "NO 0", "EL 3" or "VASS 1"
    model_params: SARIMAX settings, any of p, d, q (AR order, differencing, MA order),
        sp, sd, sq (the same for the seasonal part, period 52 weeks) and learning_rate
        (for the online linear regression inside SNARIMAX); missing ones come from DEFAULTS
    history_years: how many years of history the model learns from
    horizon_weeks: how many weeks ahead to forecast (13 weeks is about 3 months)
    sources: data sources used as inputs, any of "weather" and "exchange_rates"
    end: last week of history (default: the latest week); used for testing on the past
    data: a table from load_data, to avoid downloading again when testing many settings

    Returns a table with the forecast for each future week (dated on Sunday).
    """
    sources = tuple(sources)
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise ValueError(f"Unknown data sources: {unknown}. Choose from {SOURCES}")
    if data is None:
        # only the weeks needed, so the weather download stays small
        latest = load_filling(area).last_valid_index() if end is None else pd.Timestamp(end)
        data = load_data(area, sources, start=latest - pd.DateOffset(years=history_years), end=latest)
    end = pd.Timestamp(end) if end is not None else data["filling"].last_valid_index()
    start = end - pd.DateOffset(years=history_years)
    exog_cols = [col for source in sources for col in SOURCE_COLUMNS[source]]
    history = data.loc[start:end, ["filling"] + exog_cols].interpolate(limit_direction="both")   # fills the odd missing week

    future_dates = pd.date_range(end + pd.Timedelta(weeks=1), periods=horizon_weeks, freq="W-SUN")
    future_exog = _future_exog(data.loc[:end], exog_cols, future_dates)

    values = _fit_forecast(history, exog_cols, future_exog, horizon_weeks, model_params or {})
    return pd.DataFrame({"forecast": values}, index=future_dates.rename("date"))


def forecast_window(data, start, end, horizon_weeks, exog_cols=(), model_params=None, future_exog="normal"):
    """Dynamic forecast from a chosen training period, for the Streamlit forecast page.

    data: weekly table (dated on Sundays) with a "filling" column and any exogenous columns
    start, end: first and last week of the training data
    exog_cols: the columns of data to use as exogenous variables
    future_exog: "normal" uses the normal value for the week of the year (weather) or the last
        known value (exchange rate), as in a real forecast; "observed" uses what really happened,
        where it is known (only possible when forecasting from a week in the past)

    The forecast is dynamic: each week ahead builds on the model's own forecasts for the weeks
    before, not on observed filling.
    """
    exog_cols = list(exog_cols)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    history = data.loc[start:end, ["filling"] + exog_cols].interpolate(limit_direction="both")
    dates = pd.date_range(end + pd.Timedelta(weeks=1), periods=horizon_weeks, freq="W-SUN")
    future = _future_exog(data.loc[:end], exog_cols, dates)
    if future_exog == "observed" and exog_cols:
        future = data[exog_cols].reindex(dates).fillna(future)
    values = _fit_forecast(history, exog_cols, future, horizon_weeks, model_params or {})
    return pd.Series(values, index=dates.rename("date"), name="forecast")


def quantile_bands(data, start, end, horizon_weeks, exog_cols=(), model_params=None,
                   levels=(0.8, 0.9), future_exog="normal", growth=INTERVAL_GROWTH):
    """Confidence intervals from SARIMAX models trained with quantile loss.

    For a level of 90 %, two extra SARIMAX models with the same settings are trained with
    optim.losses.Quantile(alpha=0.05) and (alpha=0.95): they learn the lower and upper bound one
    week ahead. Forecasting them 13 weeks ahead on their own makes the bands far too wide, because
    each model builds on its own low or high values, so the one-week interval is widened with the
    number of weeks ahead instead: offset * h ** growth. With growth=None, the quantile models do
    forecast all the weeks on their own (only for comparing the two in the notebook).

    Returns {level: (lower, upper)} as offsets from the forecast for each week ahead, like error_bands.
    """
    exog_cols = list(exog_cols)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    history = data.loc[start:end, ["filling"] + exog_cols].interpolate(limit_direction="both")
    dates = pd.date_range(end + pd.Timedelta(weeks=1), periods=horizon_weeks, freq="W-SUN")
    future = _future_exog(data.loc[:end], exog_cols, dates)
    if future_exog == "observed" and exog_cols:
        future = data[exog_cols].reindex(dates).fillna(future)
    xs = _future_xs(future, exog_cols)

    alphas = sorted({a for level in levels for a in ((1 - level) / 2, (1 + level) / 2)})
    models = {None: _make_sarimax(model_params or {}), **{a: _make_sarimax(model_params or {}, a) for a in alphas}}
    _learn(models.values(), history, exog_cols)
    if growth is None:
        own = {a: np.clip(model.forecast(horizon_weeks, xs=xs), 0, 100) for a, model in models.items()}
        return {level: (np.minimum(own[(1 - level) / 2] - own[None], 0), np.maximum(own[(1 + level) / 2] - own[None], 0))
                for level in levels}
    one_week = {a: model.forecast(1, xs=xs[:1] if xs else None)[0] for a, model in models.items()}
    scale = np.arange(1, horizon_weeks + 1) ** growth
    bands = {}
    for level in levels:
        lower = min(one_week[(1 - level) / 2] - one_week[None], 0.0)    # never above the forecast
        upper = max(one_week[(1 + level) / 2] - one_week[None], 0.0)    # never below the forecast
        bands[level] = (lower * scale, upper * scale)
    return bands


def error_bands(data, start, end, horizon_weeks, exog_cols=(), model_params=None,
                n_origins=26, step_weeks=4, levels=(0.8, 0.95)):
    """Prediction intervals from the model's own errors on the past.

    The same model is used to forecast from up to n_origins earlier weeks inside the training
    period (every step_weeks weeks, each with at least two years of history), and the errors are
    collected for each week ahead. The interval for a level is the middle `level` share of those
    errors, added to the forecast. Returns {level: (lower, upper)} as offsets per week ahead, and
    the number of past forecasts used.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    origins = [end - pd.Timedelta(weeks=horizon_weeks + step_weeks * k) for k in range(n_origins)]
    origins = [o for o in origins if o - start >= pd.Timedelta(weeks=104)]
    errors = []
    for origin in origins:
        fc = forecast_window(data, start, origin, horizon_weeks, exog_cols, model_params)
        errors.append(data["filling"].reindex(fc.index).values - fc.values)
    if not errors:
        return {}, 0
    errors = np.vstack(errors)
    bands = {level: tuple(np.nanquantile(errors, [(1 - level) / 2, (1 + level) / 2], axis=0)) for level in levels}
    return bands, len(origins)


# ---------------------------------------------------------------------------------------------
# Testing on the past
# ---------------------------------------------------------------------------------------------

def backtest(data, origins, horizon_weeks=13, **settings):
    """Forecast from each origin (a past week) and compare with what really happened.

    Returns the mean absolute error in percentage points for each step ahead, the overall mean
    absolute error, and the time used.
    """
    t0 = time.perf_counter()
    errors = []
    for origin in origins:
        fc = forecast_filling(data=data, end=origin, horizon_weeks=horizon_weeks, **settings)
        actual = data["filling"].reindex(fc.index)
        errors.append((fc["forecast"] - actual).abs().values)
    errors = np.vstack(errors)
    return {
        "mae": float(np.nanmean(errors)),
        "mae_by_step": np.nanmean(errors, axis=0),
        "seconds": time.perf_counter() - t0,
    }


def baseline_forecasts(data, origins, horizon_weeks=13):
    """Two simple forecasts to compare with: the filling stays where it is ("last value"), and
    it changes like it did the same weeks last year ("last year's change")."""
    results = {}
    for name in ["last value", "last year's change"]:
        errors = []
        for origin in origins:
            dates = pd.date_range(origin + pd.Timedelta(weeks=1), periods=horizon_weeks, freq="W-SUN")
            last = data.loc[origin, "filling"]
            if name == "last value":
                fc = np.full(horizon_weeks, last)
            else:
                year_ago = data["filling"].reindex(dates - pd.Timedelta(weeks=52)).values
                fc = last + year_ago - data["filling"].get(origin - pd.Timedelta(weeks=52), np.nan)
            errors.append(np.abs(fc - data["filling"].reindex(dates).values))
        errors = np.vstack(errors)
        results[name] = {"mae": float(np.nanmean(errors)), "mae_by_step": np.nanmean(errors, axis=0)}
    return results
