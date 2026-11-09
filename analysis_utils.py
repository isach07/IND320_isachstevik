import numpy as np
import pandas as pd
from scipy.fft import dct, idct
from scipy.signal import spectrogram
from sklearn.neighbors import LocalOutlierFactor
from statsmodels.tsa.seasonal import STL

# The same analyses as in the part 3 notebook (precipitation_outliers, temperature_anomalies,
# stl_fill_ratio and spectrogram_fill_ratio), but they return the numbers instead of a
# matplotlib figure, so the app can draw them with plotly.

WEEKS_PER_YEAR = 52


# STL of a weekly series: returns a data frame with observed, trend, seasonal and residual.
# seasonal must be odd and at least 7; trend must be odd and longer than the period.
def stl_decompose(series, seasonal=13, trend=105, robust=True, period=WEEKS_PER_YEAR):
    if seasonal < 7 or seasonal % 2 == 0:
        raise ValueError("seasonal must be odd and at least 7")
    if trend <= period or trend % 2 == 0:
        raise ValueError(f"trend must be odd and longer than the period ({period})")
    result = STL(series, period=period, seasonal=seasonal, trend=trend, robust=robust).fit()
    return pd.DataFrame({
        "Observed": result.observed,
        "Trend": result.trend,
        "Seasonal": result.seasonal,
        "Residual": result.resid,
    })


# spectrogram of a weekly series. Frequencies are in cycles per year (52 samples per year).
# returns the frequencies, the date at the centre of each window and the power in dB.
def spectrogram_weekly(series, window=156, overlap=130):
    if not 2 <= window <= len(series):
        raise ValueError(f"window must be between 2 and {len(series)} weeks")
    if not 0 <= overlap < window:
        raise ValueError("overlap must be at least 0 and less than window")
    frequencies, times, power = spectrogram(
        series.to_numpy(), fs=WEEKS_PER_YEAR, nperseg=window, noverlap=overlap
    )
    power_db = 10 * np.log10(power + 1e-12)  # avoid log(0)
    window_centres = series.index[0] + pd.to_timedelta(times * WEEKS_PER_YEAR * 7, unit="D")  # years -> dates
    return frequencies, window_centres, power_db


# SPC outliers in a daily series (precipitation in the app).
# A DCT high-pass filter removes the seasonal curve (the first `cutoff` coefficients); the rest is
# the SATV. The boundaries are the seasonal curve + median(SATV) ± n_std × robust SD(SATV).
# returns one row per day with the boundaries and an is_outlier column, and a summary.
def spc_outliers(daily, cutoff=10, n_std=3.0):
    values = daily.to_numpy(dtype=float)
    if not 1 <= cutoff < len(values):
        raise ValueError(f"cutoff must be between 1 and {len(values) - 1}")

    coefficients = dct(values, norm="ortho")
    coefficients[cutoff:] = 0
    seasonal = idct(coefficients, norm="ortho")
    satv = values - seasonal

    # median and MAD, so the outliers themselves do not widen the boundaries
    centre = np.median(satv)
    spread = 1.4826 * np.median(np.abs(satv - centre))
    result = pd.DataFrame({
        "value": values,
        "seasonal": seasonal,
        "lower": seasonal + centre - n_std * spread,
        "upper": seasonal + centre + n_std * spread,
        "satv": satv,
    }, index=daily.index)
    result["is_outlier"] = (result["value"] > result["upper"]) | (result["value"] < result["lower"])
    result["direction"] = np.where(result["value"] > result["upper"], "above",
                                   np.where(result["value"] < result["lower"], "below", ""))

    outliers = result[result["is_outlier"]]
    summary = {
        "days": len(result),
        "outliers": len(outliers),
        "above": int((outliers["direction"] == "above").sum()),
        "below": int((outliers["direction"] == "below").sum()),
        "seasonal_cycles_longer_than_days": 2 * len(result) / cutoff,
        "satv_median": float(centre),
        "satv_robust_sd": float(spread),
        "share_of_total": float(outliers["value"].sum() / values.sum()) if values.sum() else 0.0,
    }
    return result, summary


# LOF anomalies in a daily series (temperature in the app).
# Each day is a point (date, value), both standardised, so a day is unusual when it differs from
# the days around it. `proportion` is the share of days marked (LOF's contamination).
# returns one row per day with the LOF score and an is_outlier column, and a summary.
def lof_anomalies(daily, proportion=0.01, n_neighbors=20):
    if not 0 < proportion <= 0.5:
        raise ValueError("proportion must be above 0 and at most 0.5")
    values = daily.to_numpy(dtype=float)
    days = np.arange(len(values))
    features = np.column_stack([
        (days - days.mean()) / days.std(),
        (values - values.mean()) / values.std(),
    ])
    lof = LocalOutlierFactor(n_neighbors=n_neighbors, contamination=proportion)
    is_outlier = lof.fit_predict(features) == -1

    result = pd.DataFrame({
        "value": values,
        # the median of the two weeks around each day, to say if an outlier was warm or cold
        "local_median": daily.rolling(15, center=True, min_periods=1).median().to_numpy(),
        "lof_score": -lof.negative_outlier_factor_,  # around 1 is normal, higher is more unusual
        "is_outlier": is_outlier,
    }, index=daily.index)
    result["difference"] = result["value"] - result["local_median"]
    result["direction"] = np.where(result["difference"] > 0, "higher", "lower")

    outliers = result[result["is_outlier"]]
    summary = {
        "days": len(result),
        "outliers": len(outliers),
        "higher": int((outliers["direction"] == "higher").sum()),
        "lower": int((outliers["direction"] == "lower").sum()),
        "largest_difference": float(outliers["difference"].abs().max()) if len(outliers) else 0.0,
        "lof_threshold": float(-lof.offset_),
    }
    return result, summary
