"""
Indice de stabilité (IS) de l'humidité sur 10 ans, à partir de la seule position.

Livrable : UN SEUL indice, entre 0 (très instable) et 1 (très stable).

Méthode :
  1. On garde les 10 dernières années complètes.
  2. Moyennes mensuelles de l'humidité du sol (GWETROOT) et de l'air (RH2M) : 12 mois x 10 ans.
  3. Pour chaque mois, sur les 10 années :
        IS_mois = 1 - 1/2 * [ min(D / D_REF, 1) + P ]
        Sol : D = CV des résidus (écart-type / moyenne) après suppression de la tendance,
              P = part des années à plus de 25 % de la tendance
        Air : D = écart-type des résidus (points de %),
              P = part des années à plus de 10 points de la tendance
  4. IS sol = moyenne des 12 mois ; IS air = moyenne des 12 mois.
  5. IS humidité = moyenne (IS sol, IS air).
"""
import numpy as np
import pandas as pd

NOMS_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
             "juil.", "août", "sept.", "oct.", "nov.", "déc."]

NB_ANNEES = 10
D_REF_SOL, DELTA_SOL = 0.5, 0.25     # CV de référence ; écart relatif à la tendance (25 %)
D_REF_AIR, DELTA_AIR = 10.0, 10.0    # points de % ; écart à la tendance (10 points)


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
    residus = y - tendance                     # un assèchement régulier n'est pas de l'instabilité
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
    """IS de chaque mois, pour le sol et l'air (utilisé pour le calcul final et pour la courbe)."""
    annee_debut, annee_fin = periode_dix_ans(df, nb_annees)
    mensuel = df.loc[f"{annee_debut}-01-01":f"{annee_fin}-12-31", ["sol", "air"]].resample("MS").mean()
    resultats = []
    for m in range(1, 13):
        serie = mensuel[mensuel.index.month == m]
        resultats.append({
            "mois": NOMS_MOIS[m - 1],
            "is_sol": indice_stabilite(serie.index.year, serie["sol"].values, D_REF_SOL, DELTA_SOL, relatif=True),
            "is_air": indice_stabilite(serie.index.year, serie["air"].values, D_REF_AIR, DELTA_AIR),
        })
    return resultats, annee_debut, annee_fin


def _moyenne(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    return round(float(np.mean(valeurs)), 2) if valeurs else None


def analyser_humidite(df, nb_annees=NB_ANNEES):
    """Livrable : un seul indice de stabilité de l'humidité (moyenne sol + air)."""
    mois, annee_debut, annee_fin = is_par_mois(df, nb_annees)
    is_sol = _moyenne([m["is_sol"] for m in mois])
    is_air = _moyenne([m["is_air"] for m in mois])
    return {
        "is_humidite": _moyenne([is_sol, is_air]),
        "parametres": {
            "variables": "GWETROOT (humidite du sol, zone racinaire) + RH2M (humidite de l'air)",
            "periode": f"{annee_debut}-{annee_fin}",
            "formule": "IS_mois = 1 - 0.5 * (min(D / D_REF, 1) + P) ; IS sol et IS air = moyenne des 12 mois ; "
                       "IS humidite = moyenne(IS sol, IS air)",
            "sol": {"D": "CV des residus", "D_REF": D_REF_SOL, "DELTA_relatif": DELTA_SOL},
            "air": {"D": "ecart-type des residus (points %)", "D_REF": D_REF_AIR, "DELTA_points": DELTA_AIR},
        },
    }
