"""Indice de stabilité de l'humidité (sol + air) sur 10 ans (NASA POWER)."""
from datetime import date

from .analyse import NB_ANNEES, analyser_humidite
from .power_api import telecharger_humidite


def analyse_humidite(latitude, longitude, dossier_cache="cache"):
    """
    Fonction principale appelée par le backend.
    Entrées : latitude, longitude
    Sortie  : {"is_humidite": 0.74, "parametres": {...}}
    """
    annee_fin = date.today().year
    df = telecharger_humidite(latitude, longitude, annee_fin - NB_ANNEES - 1, annee_fin,
                              dossier_cache=dossier_cache)
    return analyser_humidite(df)


__all__ = ["analyse_humidite", "analyser_humidite", "telecharger_humidite"]
