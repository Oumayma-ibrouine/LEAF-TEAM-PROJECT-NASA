"""Données SIMULÉES pour tester sans Internet (ne pas utiliser pour de vraies recommandations)."""
import numpy as np
import pandas as pd


def generer_donnees_demo(annee_debut, annee_fin, graine=0):
    rng = np.random.default_rng(graine)
    jours = pd.date_range(f"{annee_debut}-01-01", f"{annee_fin}-12-31")
    saison = -np.cos(2 * np.pi * (jours.dayofyear.values - 15) / 365.25)
    rechauffement = (jours.year.values - annee_debut) * 0.04
    # chaque mois de chaque année a sa propre anomalie : c'est elle que l'IS mesure
    cle_mois = (jours.year.values - annee_debut) * 12 + jours.month.values - 1
    anomalie_mois = rng.normal(0, 1.2, cle_mois.max() + 1)[cle_mois]
    tmoy = 17 + 9 * saison + rechauffement + anomalie_mois + rng.normal(0, 2, len(jours))
    tmax = tmoy + 7 + rng.normal(0, 1, len(jours))
    tmin = tmoy - 7 + rng.normal(0, 1, len(jours))
    return pd.DataFrame({"tmoy": tmoy.round(2), "tmax": tmax.round(2), "tmin": tmin.round(2)}, index=jours)
