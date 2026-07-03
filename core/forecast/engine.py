"""
Forecasting Engine — auto-selects the best model and returns forecast + confidence bands.

Model selection logic:
  < 30 data points   → Linear Trend (sklearn LinearRegression)
  30–500 data points → ARIMA via statsmodels (auto order selection)
  > 500 data points  → ARIMA with fixed simple order (1,1,1) for speed

All models return a ForecastResult with forecast values and confidence intervals
as Plotly-ready DataFrames.

Note: Prophet is intentionally excluded — it requires C++ build tools (pystan)
which are not guaranteed on Windows. statsmodels ARIMA is pure Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from loguru import logger


@dataclass
class ForecastResult:
    """Complete forecast output ready for Plotly rendering."""
    model_name: str
    horizon: int
    historical: pd.DataFrame      # cols: date, value
    forecast: pd.DataFrame        # cols: date, forecast, lower, upper
    metrics: dict                 # e.g. {'rmse': ..., 'mape': ...}
    figure: Optional[go.Figure] = None


# ── Internal model implementations ───────────────────────────────────────────

def _linear_forecast(
    ts: pd.Series,
    dates: pd.Series,
    horizon: int,
) -> ForecastResult:
    """
    Fit a simple OLS linear trend and project forward.
    Used when n < 30 (too few points for ARIMA).
    """
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_squared_error

    x = np.arange(len(ts)).reshape(-1, 1)
    y = ts.values
    model = LinearRegression().fit(x, y)
    y_hat = model.predict(x)
    rmse  = float(np.sqrt(mean_squared_error(y, y_hat)))
    std   = float(np.std(y - y_hat))

    # Forecast
    x_fut = np.arange(len(ts), len(ts) + horizon).reshape(-1, 1)
    fut_vals = model.predict(x_fut)

    # Date extrapolation
    if pd.api.types.is_datetime64_any_dtype(dates):
        delta = dates.diff().median()
        fut_dates = pd.date_range(
            start=dates.iloc[-1] + delta, periods=horizon, freq=delta
        )
    else:
        fut_dates = pd.RangeIndex(len(ts), len(ts) + horizon)

    hist_df = pd.DataFrame({"date": dates.values, "value": ts.values})
    fc_df   = pd.DataFrame({
        "date":     fut_dates,
        "forecast": fut_vals,
        "lower":    fut_vals - 1.96 * std,
        "upper":    fut_vals + 1.96 * std,
    })
    return ForecastResult(
        model_name="Linear Trend",
        horizon=horizon,
        historical=hist_df,
        forecast=fc_df,
        metrics={"rmse": round(rmse, 4)},
    )


def _arima_forecast(
    ts: pd.Series,
    dates: pd.Series,
    horizon: int,
) -> ForecastResult:
    """
    Fit ARIMA(1,1,1) and project forward with 95% confidence intervals.
    Used when n >= 30.
    """
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    import warnings

    order = (1, 1, 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        try:
            model  = ARIMA(ts.values, order=order).fit()
        except Exception:
            # Fallback to simpler order if convergence fails
            model = ARIMA(ts.values, order=(1, 1, 0)).fit()

    fc_res  = model.get_forecast(steps=horizon)
    fc_mean = fc_res.predicted_mean
    fc_ci   = fc_res.conf_int(alpha=0.05)
    resid   = model.resid
    rmse    = float(np.sqrt(np.mean(resid ** 2)))

    # conf_int() returns DataFrame in older statsmodels, ndarray in newer
    if hasattr(fc_ci, "iloc"):
        ci_lower = fc_ci.iloc[:, 0].values
        ci_upper = fc_ci.iloc[:, 1].values
    else:
        ci_lower = np.asarray(fc_ci)[:, 0]
        ci_upper = np.asarray(fc_ci)[:, 1]

    if pd.api.types.is_datetime64_any_dtype(dates):
        delta = dates.diff().median()
        fut_dates = pd.date_range(
            start=dates.iloc[-1] + delta, periods=horizon, freq=delta
        )
    else:
        fut_dates = pd.RangeIndex(len(ts), len(ts) + horizon)

    hist_df = pd.DataFrame({"date": dates.values, "value": ts.values})
    fc_df   = pd.DataFrame({
        "date":     fut_dates,
        "forecast": np.asarray(fc_mean),
        "lower":    ci_lower,
        "upper":    ci_upper,
    })
    return ForecastResult(
        model_name=f"ARIMA{order}",
        horizon=horizon,
        historical=hist_df,
        forecast=fc_df,
        metrics={"rmse": round(rmse, 4)},
    )


# ── Public entry point ────────────────────────────────────────────────────────

def run_forecast(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    horizon: int = 12,
) -> ForecastResult:
    """
    Auto-select and run the best forecasting model for the given time series.

    Args:
        df:        The DataFrame containing the time series.
        date_col:  Name of the date/time column.
        value_col: Name of the numeric value column to forecast.
        horizon:   Number of future periods to predict.

    Returns:
        ForecastResult with historical data, forecast, confidence bands,
        model name, and error metrics.
    """
    ts_df = df[[date_col, value_col]].copy()
    ts_df[date_col] = pd.to_datetime(ts_df[date_col], errors="coerce")
    ts_df = ts_df.dropna().sort_values(date_col).reset_index(drop=True)

    ts    = ts_df[value_col].astype(float)
    dates = ts_df[date_col]
    n     = len(ts)

    logger.info(
        f"Forecasting '{value_col}' — {n} data points, horizon={horizon}"
    )

    if n < 10:
        raise ValueError(
            f"Not enough data points for forecasting ({n} rows). Need at least 10."
        )

    # Seasonality-aware model when the series has enough full cycles (C1):
    # daily data → weekly cycle (7); monthly data → annual cycle (12).
    season = _infer_seasonal_period(dates)
    if season and n >= 2 * season + 6:
        hw = _holt_winters_forecast(ts, dates, horizon, season)
        if hw is not None:
            logger.info(f"Using Holt-Winters model (seasonal period={season})")
            hw.figure = _build_figure(hw)
            return hw

    if n < 30:
        logger.info("Using Linear Trend model (n < 30)")
        result = _linear_forecast(ts, dates, horizon)
    else:
        logger.info("Using ARIMA(1,1,1) model (n >= 30)")
        result = _arima_forecast(ts, dates, horizon)

    result.figure = _build_figure(result)
    return result


def _infer_seasonal_period(dates: pd.Series) -> int:
    """Seasonal cycle length from the series' spacing: 7 for daily, 12 for
    monthly. Weekly/quarterly series get no seasonal model (cycles too long)."""
    if len(dates) < 3:
        return 0
    step = dates.diff().dt.days.dropna().median()
    if step <= 1.5:
        return 7
    if 26 <= step <= 32:
        return 12
    return 0


def _holt_winters_forecast(ts: pd.Series, dates: pd.Series, horizon: int,
                           season: int):
    """Additive Holt-Winters with confidence band from in-sample residuals."""
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        model = ExponentialSmoothing(
            ts.values.astype(float), trend="add", seasonal="add",
            seasonal_periods=season, initialization_method="estimated",
        ).fit(optimized=True)
        fitted = pd.Series(model.fittedvalues)
        resid_sd = float((ts.values - fitted.values).std())
        fc_vals = model.forecast(horizon)

        step = dates.diff().median()
        future_dates = pd.Series(
            [dates.iloc[-1] + step * (i + 1) for i in range(horizon)])
        band = 1.96 * resid_sd
        forecast_df = pd.DataFrame({
            "date": future_dates,
            "forecast": fc_vals,
            "lower": fc_vals - band,
            "upper": fc_vals + band,
        })
        mask = fitted.notna() & pd.Series(ts.values).notna()
        denom = pd.Series(ts.values)[mask].replace(0, pd.NA).dropna()
        mape = None
        if len(denom):
            err = (pd.Series(ts.values)[mask] - fitted[mask]).abs()
            mape = float((err[denom.index] / denom.abs()).mean() * 100)
        return ForecastResult(
            model_name=f"Holt-Winters (seasonal, period={season})",
            horizon=horizon,
            historical=pd.DataFrame({"date": dates, "value": ts.values}),
            forecast=forecast_df,
            metrics={"mape": round(mape, 2) if mape is not None else None,
                     "resid_sd": round(resid_sd, 4)},
        )
    except Exception as exc:
        logger.debug(f"Holt-Winters failed, falling back: {exc}")
        return None


def _build_figure(result: ForecastResult) -> go.Figure:
    """
    Build a Plotly figure combining historical data + forecast + confidence band.

    Args:
        result: A ForecastResult from run_forecast().

    Returns:
        A Plotly Figure object ready to pass to st.plotly_chart().
    """
    fig = go.Figure()

    # Historical
    fig.add_trace(go.Scatter(
        x=result.historical["date"], y=result.historical["value"],
        mode="lines+markers", name="Historical",
        line=dict(color="#4C9BE8"),
    ))

    # Confidence band (filled area)
    fig.add_trace(go.Scatter(
        x=pd.concat([result.forecast["date"], result.forecast["date"][::-1]]),
        y=pd.concat([result.forecast["upper"], result.forecast["lower"][::-1]]),
        fill="toself", fillcolor="rgba(255,165,0,0.2)",
        line=dict(color="rgba(255,255,255,0)"),
        name="95% Confidence Band",
        showlegend=True,
    ))

    # Forecast line
    fig.add_trace(go.Scatter(
        x=result.forecast["date"], y=result.forecast["forecast"],
        mode="lines+markers", name=f"Forecast ({result.model_name})",
        line=dict(color="orange", dash="dash", width=2),
    ))

    fig.update_layout(
        title=f"Forecast — {result.model_name} | RMSE: {result.metrics.get('rmse', 'N/A')}",
        xaxis_title="Date",
        yaxis_title="Value",
        template="seaborn",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig
