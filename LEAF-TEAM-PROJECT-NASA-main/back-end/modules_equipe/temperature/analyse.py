"""
Indice de stabilité (IS) de la température sur 10 ans, à partir de la seule position.

Livrable : UN SEUL indice, entre 0 (très instable) et 1 (très stable).

Méthode :
  1. On garde les 10 dernières années complètes.
  2. Moyenne mensuelle de la température moyenne (T2M) : 12 mois x 10 ans.
  3. Pour chaque mois (janvier, février, ...), sur les 10 années :
        IS_mois = 1 - 1/2 * [ min(sigma / D_REF, 1) + P ]
        sigma = écart-type après suppression de la tendance (°C)
        P     = part des années qui s'écartent de la tendance de plus de DELTA (°C)
  4. IS température = moyenne des 12 IS mensuels.
"""
import numpy as np
import pandas as pd

NOMS_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
             "juil.", "août", "sept.", "oct.", "nov.", "déc."]

NB_ANNEES = 10
D_REF_TEMP = 3.0          # °C : écart-type considéré comme variabilité maximale
DELTA_TEMP = 2.0          # °C : écart à la tendance qui rend une année "anormale"


def indice_stabilite(annees, valeurs, d_ref, delta, relatif=False):
    """
    IS d'une série (une valeur par année pour un même mois). Retourne un nombre entre 0 et 1 (ou None).
    relatif=False : D = écart-type des résidus, P = part des |résidus| > delta
    relatif=True  : D = écart-type des résidus / moyenne (CV), P = part des |résidus| > delta x tendance
    """
    x = np.asarray(annees, dtype=float)
    y = np.asarray(valeurs, dtype=float)
    ok = ~np.isnan(y)
    x, y = x[ok], y[ok]
    if len(y) < 5:
        return None

    a, b = np.polyfit(x, y, 1)                 # tendance
    tendance = a * x + b
    residus = y - tendance                     # un réchauffement régulier n'est pas de l'instabilité
    sigma = float(np.std(residus, ddof=1))

    if relatif:
        moyenne = float(np.mean(y))
        if moyenne <= 0:
            return None
        d = sigma / moyenne
        p = float(np.mean(np.abs(residus) > delta * np.abs(tendance)))
    else:
        d = sigma
        p = float(np.mean(np.abs(residus) > delta))
    return round(1 - 0.5 * (min(d / d_ref, 1.0) + p), 2)


def periode_dix_ans(df, nb_annees=NB_ANNEES):
    """Les nb_annees dernières années complètes présentes dans les données."""
    derniere = df.index.max()
    annee_fin = derniere.year if (derniere.month, derniere.day) == (12, 31) else derniere.year - 1
    return annee_fin - nb_annees + 1, annee_fin


def is_par_mois(df, nb_annees=NB_ANNEES):
    """IS de chaque mois (utilisé pour le calcul final et pour la courbe)."""
    annee_debut, annee_fin = periode_dix_ans(df, nb_annees)
    mensuel = df.loc[f"{annee_debut}-01-01":f"{annee_fin}-12-31", "tmoy"].resample("MS").mean()
    resultats = []
    for m in range(1, 13):
        serie = mensuel[mensuel.index.month == m]
        resultats.append({"mois": NOMS_MOIS[m - 1],
                          "is": indice_stabilite(serie.index.year, serie.values, D_REF_TEMP, DELTA_TEMP)})
    return resultats, annee_debut, annee_fin


def analyser_temperature(df, nb_annees=NB_ANNEES):
    """Livrable : un seul indice de stabilité de la température."""
    mois, annee_debut, annee_fin = is_par_mois(df, nb_annees)
    valeurs = [m["is"] for m in mois if m["is"] is not None]
    return {
        "is_temperature": round(float(np.mean(valeurs)), 2) if valeurs else None,
        "parametres": {
            "variable": "T2M (temperature moyenne de l'air a 2 m)",
            "periode": f"{annee_debut}-{annee_fin}",
            "formule": "IS_mois = 1 - 0.5 * (min(sigma / D_REF, 1) + P) ; IS = moyenne des 12 mois",
            "D_REF_degres": D_REF_TEMP, "DELTA_degres": DELTA_TEMP,
        },
    }
