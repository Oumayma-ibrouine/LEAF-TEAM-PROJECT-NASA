"""Indice de stabilité de la température sur 10 ans (NASA POWER)."""
from datetime import date

from .analyse import NB_ANNEES, analyser_temperature
from .power_api import telecharger_temperatures


def analyse_temperature(latitude, longitude, dossier_cache="cache"):
    """
    Fonction principale appelée par le backend.
    Entrées : latitude, longitude
    Sortie  : {"is_temperature": 0.82, "parametres": {...}}
    """
    annee_fin = date.today().year
    df = telecharger_temperatures(latitude, longitude, annee_fin - NB_ANNEES - 1, annee_fin,
                                  dossier_cache=dossier_cache)
    return analyser_temperature(df)


__all__ = ["analyse_temperature", "analyser_temperature", "telecharger_temperatures"]
