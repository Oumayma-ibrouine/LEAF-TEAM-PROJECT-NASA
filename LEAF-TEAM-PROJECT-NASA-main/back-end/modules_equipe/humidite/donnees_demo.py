"""Données SIMULÉES pour tester sans Internet (ne pas utiliser pour de vraies recommandations)."""
import numpy as np
import pandas as pd


def generer_donnees_demo(annee_debut, annee_fin, graine=1):
    rng = np.random.default_rng(graine)
    jours = pd.date_range(f"{annee_debut}-01-01", f"{annee_fin}-12-31")
    hiver = np.cos(2 * np.pi * (jours.dayofyear.values - 15) / 365.25)       # +1 en janvier, -1 en juillet
    cle_mois = (jours.year.values - annee_debut) * 12 + jours.month.values - 1
    anomalie_sol = rng.normal(0, 0.05, cle_mois.max() + 1)[cle_mois]
    anomalie_air = rng.normal(0, 4, cle_mois.max() + 1)[cle_mois]
    sol = np.clip(0.42 + 0.2 * hiver - (jours.year.values - annee_debut) * 0.004 + anomalie_sol
                  + rng.normal(0, 0.02, len(jours)), 0.05, 0.95)
    air = np.clip(62 + 15 * hiver + anomalie_air + rng.normal(0, 6, len(jours)), 15, 100)
    return pd.DataFrame({"sol": sol.round(3), "air": air.round(1)}, index=jours)
