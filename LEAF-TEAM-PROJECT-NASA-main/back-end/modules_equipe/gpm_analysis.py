from __future__ import annotations

import argparse
import calendar
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import ee
import numpy as np
import pandas as pd
import plotly.graph_objects as go


DATASET_ID = "NASA/GPM_L3/IMERG_MONTHLY_V07"
BAND = "precipitation"
PIXEL_SCALE_METERS = 11132
DEFAULT_PERIOD_YEARS = 10

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]


def resolve_year_range(start_year=None, end_year=None):
    """Default: latest 10 complete calendar years."""
    latest = datetime.now(timezone.utc).year - 1

    if start_year is None and end_year is None:
        end_year = latest
        start_year = latest - DEFAULT_PERIOD_YEARS + 1

    elif start_year is not None and end_year is None:
        end_year = start_year + DEFAULT_PERIOD_YEARS - 1

    elif start_year is None and end_year is not None:
        start_year = end_year - DEFAULT_PERIOD_YEARS + 1

    if start_year < 2015:
        raise ValueError("GPM start year must be 2015 or later.")

    if end_year < start_year:
        raise ValueError("end_year must be >= start_year.")

    if end_year > latest:
        raise ValueError(
            f"For complete-year comparison, end_year must be {latest} or earlier."
        )

    return int(start_year), int(end_year)


def initialize_earth_engine(project=None):
    project = project or os.getenv("EE_PROJECT")

    if not project or project == "YOUR_PROJECT_ID":
        raise RuntimeError(
            "Set EE_PROJECT or pass --project with your real Google Cloud "
            "project ID; authenticate using earthengine authenticate."
        )

    try:
        ee.Initialize(project=project)
    except Exception as exc:
        raise RuntimeError(
            f"Earth Engine initialization failed for project {project}. "
            "Check API enablement, EE registration and authentication."
        ) from exc


def fetch_monthly_pixel_values(
    latitude, longitude, start_year, end_year
):
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")

    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")

    point = ee.Geometry.Point([longitude, latitude])

    collection = (
        ee.ImageCollection(DATASET_ID)
        .filterDate(
            f"{start_year}-01-01",
            f"{end_year + 1}-01-01"
        )
        .select(BAND)
        .sort("system:time_start")
    )

    def to_feature(image):
        image = ee.Image(image)

        value = image.reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=point,
            scale=PIXEL_SCALE_METERS,
            maxPixels=1000000
        ).get(BAND)

        return ee.Feature(None, {
            "timestamp": image.get("system:time_start"),
            "rate_mm_hr": value,
            "image_id": image.get("system:index")
        })

    fc = ee.FeatureCollection(
        collection.map(to_feature)
    ).filter(
        ee.Filter.notNull(["timestamp", "rate_mm_hr"])
    )

    features = fc.getInfo().get("features", [])
    records = []

    for feature in features:
        props = feature.get("properties", {})

        if props.get("timestamp") is None:
            continue

        if props.get("rate_mm_hr") is None:
            continue

        date = pd.to_datetime(
            int(props["timestamp"]),
            unit="ms",
            utc=True
        )

        year = int(date.year)
        month = int(date.month)
        rate = float(props["rate_mm_hr"])

        if not np.isfinite(rate):
            continue

        # Project assumption: precipitation band is a mean rate in mm/hr.
        # Verify the official dataset band definition and units.
        monthly_mm = (
            rate * 24 * calendar.monthrange(year, month)[1]
        )

        records.append({
            "date": date.strftime("%Y-%m-%d"),
            "year": year,
            "month": month,
            "month_name": MONTH_NAMES[month - 1],
            "precipitation_rate_mm_hr": rate,
            "precipitation_mm": monthly_mm,
            "image_id": props.get("image_id")
        })

    if not records:
        raise RuntimeError(
            "No valid GPM values returned. Check coordinates, date range, "
            "dataset and Earth Engine permissions."
        )

    return (
        pd.DataFrame(records)
        .drop_duplicates(["year", "month"], keep="last")
        .sort_values(["year", "month"])
        .reset_index(drop=True)
    )


def add_missing_months(observed, start_year, end_year):
    dates = pd.date_range(
        f"{start_year}-01-01",
        f"{end_year}-12-01",
        freq="MS"
    )

    data = observed.copy()
    data["date"] = pd.to_datetime(data["date"])

    data = data.set_index("date").reindex(dates)
    data.index.name = "date"
    data = data.reset_index()

    data["year"] = data["date"].dt.year
    data["month"] = data["date"].dt.month

    data["month_name"] = data["month"].map(
        lambda m: MONTH_NAMES[int(m) - 1]
    )

    # Missing months remain NaN, never zero.
    return data


def calculate_stability(annual_totals):
    """
    LEAF-defined Rainfall Stability Index (RSI).

    CV (%) = population standard deviation / mean * 100
    RSI (%) = max(0, 100 - CV)

    This is a project-defined descriptive index,
    not an official NASA index.
    """

    values = annual_totals.dropna().astype(float).to_numpy()

    if len(values) < 2:
        return {
            "rsi_percent": None,
            "cv_percent": None,
            "mean_annual_precipitation_mm": (
                round(float(np.mean(values)), 2)
                if len(values) else None
            ),
            "annual_standard_deviation_mm": None,
            "complete_years_used": int(len(values)),
            "interpretation": (
                "At least 2 complete years are required."
            )
        }

    mean_p = float(np.mean(values))
    std_p = float(np.std(values, ddof=0))

    if mean_p <= 0:
        return {
            "rsi_percent": None,
            "cv_percent": None,
            "mean_annual_precipitation_mm": round(mean_p, 2),
            "annual_standard_deviation_mm": round(std_p, 2),
            "complete_years_used": int(len(values)),
            "interpretation": (
                "Mean annual rainfall must be positive."
            )
        }

    cv = std_p / mean_p * 100
    rsi = max(0.0, 100.0 - cv)

    if rsi >= 80:
        label = "Very stable"
    elif rsi >= 60:
        label = "Fairly stable"
    elif rsi >= 40:
        label = "Moderately stable"
    elif rsi >= 20:
        label = "Unstable"
    else:
        label = "Highly variable"

    return {
        "rsi_percent": round(rsi, 2),
        "cv_percent": round(cv, 2),
        "mean_annual_precipitation_mm": round(mean_p, 2),
        "annual_standard_deviation_mm": round(std_p, 2),
        "complete_years_used": int(len(values)),
        "interpretation": label
    }


def calculate_statistics(data):
    rows = []

    for year, group in data.groupby("year"):
        vals = group["precipitation_mm"].dropna()
        count = int(vals.count())
        complete = count == 12

        rows.append({
            "year": int(year),
            "months_available": count,
            "complete_year": bool(complete),
            "annual_total_mm": (
                float(vals.sum()) if complete else None
            ),
            "observed_partial_sum_mm": (
                float(vals.sum()) if count else None
            )
        })

    annual = pd.DataFrame(rows)

    climatology = (
        data.groupby("month")["precipitation_mm"]
        .mean()
        .reindex(range(1, 13))
    )

    monthly_average = pd.DataFrame({
        "month": range(1, 13),
        "month_name": MONTH_NAMES,
        "average_mm": climatology.values
    })

    stability = calculate_stability(
        annual.loc[annual["complete_year"], "annual_total_mm"]
    )

    valid_dates = data.loc[
        data["precipitation_mm"].notna(), "date"
    ]

    summary = {
        "source": DATASET_ID,
        "band": BAND,
        "source_band_unit_assumption": "mm/hr",
        "processed_unit": "mm/month",
        "requested_start_year": int(data["year"].min()),
        "requested_end_year": int(data["year"].max()),
        "first_observation": (
            pd.to_datetime(valid_dates.min()).strftime("%Y-%m")
            if not valid_dates.empty else None
        ),
        "last_observation": (
            pd.to_datetime(valid_dates.max()).strftime("%Y-%m")
            if not valid_dates.empty else None
        ),
        "valid_month_count": int(
            data["precipitation_mm"].count()
        ),
        "missing_month_count": int(
            data["precipitation_mm"].isna().sum()
        ),
        "complete_year_count": int(
            annual["complete_year"].sum()
        ),
        "rainfall_stability": stability,
        "monthly_climatology": monthly_average.to_dict(
            orient="records"
        )
    }

    return data, annual, monthly_average, summary


def save_three_charts(
    data,
    annual,
    monthly_average,
    summary,
    latitude,
    longitude,
    output_dir
):
    output_dir.mkdir(parents=True, exist_ok=True)

    loc = f"Lat {latitude:.4f}, Lon {longitude:.4f}"
    paths = []

    # CHART 1: Monthly rainfall heatmap
    heat = (
        data.pivot(
            index="year",
            columns="month",
            values="precipitation_mm"
        )
        .reindex(columns=range(1, 13))
    )

    fig = go.Figure(go.Heatmap(
        z=heat.values,
        x=MONTH_NAMES,
        y=heat.index.astype(str),
        colorscale="Blues",
        colorbar={
            "title": "Precipitation<br>(mm/month)"
        },
        hovertemplate=(
            "Year: %{y}<br>"
            "Month: %{x}<br>"
            "Rainfall: %{z:.1f} mm<extra></extra>"
        ),
        connectgaps=False
    ))

    fig.update_layout(
        title=(
            f"Monthly precipitation — 10-year view"
            f"<br><sup>{loc}</sup>"
        ),
        template="plotly_white",
        height=max(
            550,
            min(1100, 350 + len(heat.index) * 35)
        ),
        xaxis_title="Month",
        yaxis_title="Year",
        yaxis={"autorange": "reversed"}
    )

    path = output_dir / "01_rainfall_heatmap.html"
    fig.write_html(path, include_plotlyjs=True)
    paths.append(path)

    # CHART 2: Annual totals + RSI
    complete = annual[annual["complete_year"]]
    rsi = summary["rainfall_stability"]["rsi_percent"]

    rsi_text = (
        f"Rainfall Stability Index: {rsi:.1f}%"
        if rsi is not None
        else "RSI unavailable: at least 2 complete years required"
    )

    fig = go.Figure(go.Bar(
        x=complete["year"],
        y=complete["annual_total_mm"],
        marker_color="#2878B5",
        name="Annual precipitation",
        hovertemplate=(
            "Year: %{x}<br>"
            "Total: %{y:.1f} mm<extra></extra>"
        )
    ))

    fig.update_layout(
        title=(
            f"Annual precipitation totals"
            f"<br><sup>{loc} | {rsi_text}</sup>"
        ),
        template="plotly_white",
        height=560,
        xaxis_title="Year",
        yaxis_title="Annual precipitation (mm)",
        hovermode="x unified"
    )

    path = output_dir / "02_annual_rainfall_and_stability.html"
    fig.write_html(path, include_plotlyjs=True)
    paths.append(path)

    # CHART 3: Monthly seasonal averages
    fig = go.Figure(go.Bar(
        x=monthly_average["month_name"],
        y=monthly_average["average_mm"],
        marker_color="#159D83",
        name="Average monthly precipitation",
        hovertemplate=(
            "%{x}<br>"
            "Average: %{y:.1f} mm<extra></extra>"
        )
    ))

    fig.update_layout(
        title=(
            f"Rainfall seasonality — monthly average"
            f"<br><sup>{loc}</sup>"
        ),
        template="plotly_white",
        height=520,
        xaxis_title="Month",
        yaxis_title="Average precipitation (mm/month)"
    )

    path = output_dir / "03_monthly_seasonality.html"
    fig.write_html(path, include_plotlyjs=True)
    paths.append(path)

    return paths


def export_data(
    data,
    annual,
    monthly_average,
    summary,
    latitude,
    longitude,
    start_year,
    end_year,
    output_dir
):
    output_dir.mkdir(parents=True, exist_ok=True)

    data.to_csv(
        output_dir / "gpm_monthly_data.csv",
        index=False,
        date_format="%Y-%m-%d"
    )

    def clean(frame):
        return json.loads(
            frame.to_json(
                orient="records",
                date_format="iso"
            )
        )

    payload = {
        "metadata": {
            "source": DATASET_ID,
            "band": BAND,
            "source_band_unit_assumption": "mm/hr",
            "processed_unit": "mm/month",
            "latitude": latitude,
            "longitude": longitude,
            "start_year": start_year,
            "end_year": end_year,
            "period_years_requested": end_year - start_year + 1,
            "note": (
                "Missing months are null, not zero. "
                "Annual totals and RSI use complete years only. "
                "Current extraction samples one GPM pixel at "
                "the selected point, not a farm polygon average."
            )
        },
        "summary": summary,
        "annual": clean(annual),
        "monthly_climatology": clean(monthly_average),
        "monthly_data": clean(data)
    }

    with (
        output_dir / "gpm_monthly_data.json"
    ).open("w", encoding="utf-8") as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )

    with (
        output_dir / "gpm_summary.json"
    ).open("w", encoding="utf-8") as f:
        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )


def run_analysis(
    latitude,
    longitude,
    start_year=None,
    end_year=None,
    project=None,
    output="output"
):
    start_year, end_year = resolve_year_range(
        start_year, end_year
    )

    output_dir = Path(output)

    initialize_earth_engine(project)

    print(
        f"Dataset: {DATASET_ID}\n"
        f"Point: {latitude}, {longitude}\n"
        f"Period: {start_year}-{end_year} "
        f"({end_year - start_year + 1} years)"
    )

    observed = fetch_monthly_pixel_values(
        latitude,
        longitude,
        start_year,
        end_year
    )

    full_months = add_missing_months(
        observed,
        start_year,
        end_year
    )

    data, annual, monthly_average, summary = calculate_statistics(
        full_months
    )

    print("\nRAINFALL STABILITY INDEX")
    print("-----------------------")
    print(summary["rainfall_stability"])

    charts = save_three_charts(
        data,
        annual,
        monthly_average,
        summary,
        latitude,
        longitude,
        output_dir
    )

    export_data(
        data,
        annual,
        monthly_average,
        summary,
        latitude,
        longitude,
        start_year,
        end_year,
        output_dir
    )

    print("\nSUCCESS — 3 charts and data exports created:")

    for chart_path in charts:
        print(f"  {chart_path}")

    print(f"  {output_dir / 'gpm_monthly_data.csv'}")
    print(f"  {output_dir / 'gpm_monthly_data.json'}")
    print(f"  {output_dir / 'gpm_summary.json'}")

    print(
        f"Valid months: {summary['valid_month_count']} | "
        f"Missing months: {summary['missing_month_count']} | "
        f"Complete years: {summary['complete_year_count']}"
    )

    return {
        "data": data,
        "annual": annual,
        "summary": summary,
        "charts": [str(p) for p in charts],
        "output_dir": str(output_dir)
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "LEAF GPM analysis — default latest 10 complete years"
        )
    )

    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--project", type=str, default=None)
    parser.add_argument("--output", type=str, default="output")

    args = parser.parse_args()

    run_analysis(
        args.lat,
        args.lon,
        args.start_year,
        args.end_year,
        args.project,
        args.output
    )
