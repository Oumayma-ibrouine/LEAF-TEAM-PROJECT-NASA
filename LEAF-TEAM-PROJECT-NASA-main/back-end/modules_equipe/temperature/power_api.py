"""
Téléchargement de la température journalière depuis l'API NASA POWER (sans clé).

    T2M     : température moyenne de l'air à 2 m (°C)  -> utilisée pour l'IS
    T2M_MAX : température maximale (°C)                -> affichée dans la série temporelle
    T2M_MIN : température minimale (°C)                -> affichée dans la série temporelle

Résultat : DataFrame pandas indexé par date, colonnes "tmoy", "tmax", "tmin".
"""
import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

URL_POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
VALEUR_MANQUANTE = -999
PARAMETRES = {"T2M": "tmoy", "T2M_MAX": "tmax", "T2M_MIN": "tmin"}


def telecharger_temperatures(latitude, longitude, annee_debut, annee_fin, dossier_cache="cache", timeout=180):
    """Télécharge du 1er janvier annee_debut au 31 décembre annee_fin (ou jusqu'à il y a 10 jours)."""
    fin_max = date.today() - timedelta(days=10)          # NASA POWER publie avec quelques jours de retard
    date_fin = min(date(annee_fin, 12, 31), fin_max)
    debut, fin = f"{annee_debut}0101", date_fin.strftime("%Y%m%d")

    os.makedirs(dossier_cache, exist_ok=True)
    chemin = os.path.join(dossier_cache, f"temperature_{latitude:.4f}_{longitude:.4f}_{debut}_{fin}.csv")

    if os.path.exists(chemin):
        try:
            df = pd.read_csv(chemin, index_col=0, parse_dates=True)
            print(f"[cache] Donnees chargees : {chemin}")
            return df
        except Exception:
            os.remove(chemin)

    params = {"parameters": ",".join(PARAMETRES), "community": "AG",
              "latitude": latitude, "longitude": longitude,
              "start": debut, "end": fin, "format": "JSON"}
    print("[NASA POWER] Telechargement en cours...")
    for essai in range(1, 4):
        try:
            reponse = requests.get(URL_POWER, params=params, timeout=timeout)
            reponse.raise_for_status()
            break
        except requests.RequestException as erreur:
            if essai == 3:
                raise RuntimeError(f"NASA POWER ne repond pas : {erreur}") from erreur
            print(f"[NASA POWER] Erreur (essai {essai}/3), nouvel essai dans 5 s...")
            time.sleep(5)

    brut = reponse.json()["properties"]["parameter"]
    df = pd.DataFrame({nom: brut[code] for code, nom in PARAMETRES.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.sort_index().astype(float)
    df[df <= VALEUR_MANQUANTE] = np.nan                  # -999 -> valeur manquante

    temporaire = chemin + ".tmp"
    df.to_csv(temporaire)
    os.replace(temporaire, chemin)
    print(f"[NASA POWER] {len(df)} jours sauvegardes dans : {chemin}")
    return df
