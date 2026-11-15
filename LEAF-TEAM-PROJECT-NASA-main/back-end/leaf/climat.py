"""
Données climatiques par pixel (étapes 2 et 3 du schéma).

- NASA POWER : un seul appel API par pixel 0,5° × 0,625° (température, humidité, vent, pluie journaliers),
  mis en cache par PIXEL : deux parcelles du même pixel réutilisent le même téléchargement.
- GPM IMERG (Earth Engine) : pluie mensuelle par pixel 0,1°, si EE_PROJECT est configuré ;
  sinon la pluie vient de NASA POWER (PRECTOTCORR), et la source est indiquée dans la réponse.
- Indices de stabilité : modules de l'équipe (modules_equipe/temperature, humidite, gpm_analysis).
"""
import calendar
import logging
import os
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from modules_equipe.humidite import analyse as analyse_hum
from modules_equipe.temperature import analyse as analyse_temp

from . import pixels as px

log = logging.getLogger("leaf.climat")

URL_POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETRES_POWER = {
    "T2M": "tmoy", "T2M_MAX": "tmax", "T2M_MIN": "tmin",
    "GWETROOT": "sol", "RH2M": "air", "WS2M": "vent", "PRECTOTCORR": "pluie",
}
NB_ANNEES = 10
CACHE = Path(__file__).resolve().parent.parent / "cache"

# Vent : PROVISOIRE, en attendant le module vent de l'équipe (Leaf_Project_Wind).
# Même formule que la température : IS_mois = 1 - 0.5 * (min(sigma / D_REF, 1) + P)
D_REF_VENT = 1.0     # m/s
DELTA_VENT = 0.75    # m/s


def periode():
    """Les 10 dernières années civiles complètes."""
    fin = date.today().year - 1
    return fin - NB_ANNEES + 1, fin


# ------------------------------------------------------------------ NASA POWER, par pixel
def _telecharger_pixel_power(lat, lon, debut, fin):
    CACHE.mkdir(exist_ok=True)
    chemin = CACHE / f"power_px_{lat:.4f}_{lon:.4f}_{debut}_{fin}.csv"
    if chemin.exists():
        return pd.read_csv(chemin, index_col=0, parse_dates=True)

    params = {"parameters": ",".join(PARAMETRES_POWER), "community": "AG",
              "latitude": lat, "longitude": lon,
              "start": f"{debut}0101", "end": f"{fin}1231", "format": "JSON"}
    for essai in range(3):
        try:
            r = requests.get(URL_POWER, params=params, timeout=180)
            r.raise_for_status()
            break
        except requests.RequestException as erreur:
            if essai == 2:
                raise RuntimeError(f"NASA POWER ne répond pas : {erreur}") from erreur
            time.sleep(5)
    brut = r.json()["properties"]["parameter"]
    df = pd.DataFrame({nom: brut[code] for code, nom in PARAMETRES_POWER.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.sort_index().astype(float)
    df[df <= -999] = np.nan
    tmp = chemin.with_suffix(".tmp")
    df.to_csv(tmp)
    os.replace(tmp, chemin)
    return df


def series_power(geom):
    """Série journalière de la parcelle = moyenne des pixels POWER touchés, pondérée par la surface."""
    debut, fin = periode()
    pixels = px.pixels_touches(geom, px.NASA_POWER)
    total = None
    for p in pixels:
        df = _telecharger_pixel_power(p["centre_lat"], p["centre_lon"], debut, fin)
        total = df * p["part"] if total is None else total.add(df * p["part"], fill_value=np.nan)
    return total, px.resume_pixels(geom, px.NASA_POWER, pixels)


# ------------------------------------------------------------------ GPM IMERG (Earth Engine), par pixel
@lru_cache(maxsize=1)
def _earth_engine_pret():
    projet = os.getenv("EE_PROJECT")
    if not projet:
        return False
    try:
        from modules_equipe.gpm_analysis import initialize_earth_engine
        initialize_earth_engine(projet)
        return True
    except Exception as erreur:      # pas d'identifiants, API désactivée...
        log.warning("Earth Engine indisponible : %s", erreur)
        return False


def pluie_mensuelle(geom, df_power):
    """
    Pluie mensuelle (mm) de la parcelle sur 10 ans.
    GPM IMERG 0,1° si Earth Engine est configuré, sinon NASA POWER.
    """
    debut, fin = periode()
    if _earth_engine_pret():
        from modules_equipe.gpm_analysis import add_missing_months, fetch_monthly_pixel_values
        pixels = px.pixels_touches(geom, px.GPM_IMERG)
        try:
            total = None
            for p in pixels:
                obs = fetch_monthly_pixel_values(p["centre_lat"], p["centre_lon"], debut, fin)
                mois = add_missing_months(obs, debut, fin).set_index("date")["precipitation_mm"]
                total = mois * p["part"] if total is None else total + mois * p["part"]
            return total, "GPM IMERG V07 (Google Earth Engine)", px.resume_pixels(geom, px.GPM_IMERG, pixels)
        except Exception as erreur:
            log.warning("GPM indisponible, repli sur NASA POWER : %s", erreur)

    serie = df_power["pluie"].resample("MS").sum(min_count=25)
    return serie, "NASA POWER PRECTOTCORR (GPM non configuré)", None


# ------------------------------------------------------------------ indices de stabilité
def _is_vent(df):
    debut, fin = analyse_temp.periode_dix_ans(df)
    mensuel = df.loc[f"{debut}-01-01":f"{fin}-12-31", "vent"].resample("MS").mean()
    mois = []
    for m in range(1, 13):
        s = mensuel[mensuel.index.month == m]
        mois.append({"mois": analyse_temp.NOMS_MOIS[m - 1],
                     "is": analyse_temp.indice_stabilite(s.index.year, s.values, D_REF_VENT, DELTA_VENT)})
    valeurs = [m["is"] for m in mois if m["is"] is not None]
    return {
        "is_vent": round(float(np.mean(valeurs)), 2) if valeurs else None,
        "is_par_mois": mois,
        "parametres": {
            "variable": "WS2M (vent à 2 m, NASA POWER)",
            "formule": "IS_mois = 1 - 0.5 * (min(sigma / D_REF, 1) + P)",
            "D_REF_m_s": D_REF_VENT, "DELTA_m_s": DELTA_VENT,
            "statut": "PROVISOIRE : à remplacer par le module vent de l'équipe",
        },
    }


def _is_pluie(pluie_mois):
    from modules_equipe.gpm_analysis import calculate_stability
    annees = pluie_mois.groupby(pluie_mois.index.year)
    totaux = annees.sum(min_count=12)
    rsi = calculate_stability(totaux)
    is_pluie = None if rsi["rsi_percent"] is None else round(rsi["rsi_percent"] / 100, 2)
    return {
        "is_pluie": is_pluie,
        "rsi_percent": rsi["rsi_percent"],
        "cv_percent": rsi["cv_percent"],
        "pluie_annuelle_moyenne_mm": rsi["mean_annual_precipitation_mm"],
        "annees_completes": rsi["complete_years_used"],
        "interpretation": rsi["interpretation"],
        "parametres": {"formule": "RSI = max(0, 100 - CV des cumuls annuels) ; IS pluie = RSI / 100",
                       "note": "Échelle ramenée à 0-1 pour être comparable aux autres IS"},
    }


def analyser(geom):
    df, pixels_power = series_power(geom)
    pluie_mois, source_pluie, pixels_gpm = pluie_mensuelle(geom, df)

    temp = analyse_temp.analyser_temperature(df[["tmoy", "tmax", "tmin"]])
    temp["is_par_mois"] = analyse_temp.is_par_mois(df[["tmoy", "tmax", "tmin"]])[0]
    hum = analyse_hum.analyser_humidite(df[["sol", "air"]])
    hum["is_par_mois"] = analyse_hum.is_par_mois(df[["sol", "air"]])[0]
    vent = _is_vent(df)
    pluie = _is_pluie(pluie_mois)
    pluie["source"] = source_pluie

    debut, fin = periode()
    return {
        "periode": f"{debut}-{fin}",
        "indices": {
            "temperature": temp["is_temperature"],
            "humidite": hum["is_humidite"],
            "pluie": pluie["is_pluie"],
            "vent": vent["is_vent"],
        },
        "details": {"temperature": temp, "humidite": hum, "pluie": pluie, "vent": vent},
        "pixels": {"nasa_power": pixels_power, "gpm": pixels_gpm},
        "_df": df,
        "_pluie_mois": pluie_mois,
    }


# ------------------------------------------------------------------ conditions de la saison (étape 4)
def fenetres_saison(df, date_plantation: date, cycle_jours: int):
    """Une fenêtre [plantation, plantation + cycle] par année des 10 ans."""
    fenetres = []
    for annee in sorted(set(df.index.year)):
        try:
            debut = date(annee, date_plantation.month, date_plantation.day)
        except ValueError:          # 29 février
            debut = date(annee, date_plantation.month, 28)
        fin = debut + timedelta(days=int(cycle_jours) - 1)
        if pd.Timestamp(fin) > df.index.max():
            continue
        fenetres.append((annee, pd.Timestamp(debut), pd.Timestamp(fin)))
    return fenetres


def stats_saison(df, date_plantation, cycle_jours):
    """Statistiques par année de la saison de culture (utilisées par le moteur de décision)."""
    lignes = []
    for annee, debut, fin in fenetres_saison(df, date_plantation, cycle_jours):
        p = df.loc[debut:fin]
        mensuel = p["tmoy"].resample("MS").mean()
        lignes.append({
            "annee": annee,
            "tmoy_mois_min": float(mensuel.min()),
            "tmoy_mois_max": float(mensuel.max()),
            "tmoy": float(p["tmoy"].mean()),
            "tmin_jour_min": float(p["tmin"].min()),
            "pluie_saison": float(p["pluie"].sum(min_count=int(cycle_jours * 0.9))),
            "manquants": int(p[["tmoy", "tmin", "pluie"]].isna().any(axis=1).sum()),
        })
    return pd.DataFrame(lignes)


def normales_saison(df, date_plantation, cycle_jours):
    """Normales mensuelles (moyenne 10 ans) des mois couverts par la saison, à partir de la plantation."""
    mois = []
    d = date(2001, date_plantation.month, min(date_plantation.day, 28))
    fin = d + timedelta(days=int(cycle_jours) - 1)
    while d <= fin:
        if d.month not in mois:
            mois.append(d.month)
        d += timedelta(days=1)

    mensuel = df.resample("MS").agg({"tmoy": "mean", "tmax": "mean", "tmin": "mean", "sol": "mean",
                                     "air": "mean", "vent": "mean", "pluie": "sum"})
    normales = []
    for m in mois:
        s = mensuel[mensuel.index.month == m]
        normales.append({
            "mois": m,
            "nom": analyse_temp.NOMS_MOIS[m - 1],
            "tmoy": round(float(s["tmoy"].mean()), 1),
            "tmax": round(float(s["tmax"].mean()), 1),
            "tmin": round(float(s["tmin"].mean()), 1),
            "pluie_mm": round(float(s["pluie"].mean()), 1),
            "humidite_sol": round(float(s["sol"].mean()), 2),
            "humidite_air": round(float(s["air"].mean()), 1),
            "vent_m_s": round(float(s["vent"].mean()), 2),
        })
    return normales


def pluie_annuelle(pluie_mois):
    totaux = pluie_mois.groupby(pluie_mois.index.year).sum(min_count=12)
    return totaux.dropna()


def jours_dans_mois(annee, mois):
    return calendar.monthrange(annee, mois)[1]
