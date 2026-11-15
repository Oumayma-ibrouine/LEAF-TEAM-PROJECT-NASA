"""
FAO GAEZ v5 : aptitude des terres, lue À DISTANCE (aucun fichier local) pixel par pixel (étapes 7-8).

Les rasters GAEZ v5 sont des Cloud Optimized GeoTIFF publics sur le bucket FAO :
rasterio ne télécharge que les tuiles qui couvrent la parcelle (quelques Ko), pas le fichier entier.

    HRLM = intrants élevés, PLUVIAL     HILM = intrants élevés, IRRIGUÉ
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import rasterio
from rasterio.windows import Window

from . import pixels as px

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")

log = logging.getLogger("leaf.gaez")

URL = ("/vsicurl/https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET/RES05-SIX30AS/"
       "GAEZ-V5.RES05-SIX30AS.HP0120.AGERA5.HIST.{code}.{eau}.tif")

CLASSES = {
    1: "Très haute", 2: "Haute", 3: "Bonne", 4: "Moyenne", 5: "Modérée",
    6: "Marginale", 7: "Très marginale", 8: "Non adaptée", 9: "Eau",
}

# Seuils PROVISOIRES (à valider par l'agronome)
CLASSE_SUFFISANTE = 4       # classes 1 à 4 : aptitude suffisante
CLASSE_LIMITE = 5           # classe 5 : proche du seuil -> à vérifier


def scenario_eau(irrigation: bool):
    return "HILM" if irrigation else "HRLM"


@lru_cache(maxsize=2048)
def _lire_pixels(code, eau, cellules):
    """
    Valeurs des pixels GAEZ (i, j) de la grille px.GAEZ, lues en une seule fenêtre.
    Grille px.GAEZ : bord (90° N, 180° O), donc ligne raster = -(i + 1), colonne raster = j.
    """
    lignes = [-(i + 1) for i, _ in cellules]
    colonnes = [j for _, j in cellules]
    l0, c0 = min(lignes), min(colonnes)
    with rasterio.open(URL.format(code=code, eau=eau)) as src:
        fenetre = Window(c0, l0, max(colonnes) - c0 + 1, max(lignes) - l0 + 1)
        bloc = src.read(1, window=fenetre, boundless=True, fill_value=0)
    return tuple(int(bloc[l - l0, c - c0]) for l, c in zip(lignes, colonnes))


def aptitude_culture(code, pixels, eau):
    """Aptitude d'une culture sur tous les pixels GAEZ de la parcelle."""
    try:
        lues = _lire_pixels(code, eau, tuple((p["i"], p["j"]) for p in pixels))
        valeurs = list(zip(lues, (p["part"] for p in pixels)))
    except rasterio.errors.RasterioError as erreur:
        log.warning("GAEZ %s %s illisible : %s", code, eau, erreur)
        return {"code_gaez": code, "statut": "donnees_manquantes", "erreur": str(erreur)}

    parts = {}
    for valeur, part in valeurs:
        parts[valeur] = parts.get(valeur, 0) + part
    connues = {c: p for c, p in parts.items() if c in CLASSES}
    part_inconnue = round(sum(p for c, p in parts.items() if c not in CLASSES), 4)

    if not connues:
        return {"code_gaez": code, "statut": "donnees_manquantes", "classes": {}, "part_sans_donnee": part_inconnue}

    majoritaire = max(connues, key=lambda c: (connues[c], -c))
    pire = max(connues)
    moyenne = sum(c * p for c, p in connues.items()) / sum(connues.values())
    return {
        "code_gaez": code,
        "statut": "ok",
        "scenario": eau,
        "classe_majoritaire": majoritaire,
        "aptitude": CLASSES[majoritaire],
        "pire_classe": pire,
        "classe_moyenne": round(moyenne, 2),
        "classes": {str(c): round(p, 4) for c, p in sorted(connues.items())},
        "part_sans_donnee": part_inconnue,
        "heterogene": len(connues) > 1,
    }


def decision_sol(apt):
    """Étape 8 : « Aptitude des terres suffisante ? » -> (statut, justification)."""
    if apt.get("statut") != "ok":
        return "incertitude", "Données GAEZ manquantes sur la parcelle"
    c, pire = apt["classe_majoritaire"], apt["pire_classe"]
    if c == 9:
        return "non", "Pixel GAEZ classé « Eau »"
    if apt.get("part_sans_donnee", 0) > 0.25:
        return "incertitude", f"{apt['part_sans_donnee']:.0%} de la parcelle sans donnée GAEZ"
    if c <= CLASSE_SUFFISANTE and pire <= CLASSE_SUFFISANTE:
        return "oui", f"Aptitude {CLASSES[c].lower()} (classe {c}) sur toute la parcelle"
    if c <= CLASSE_SUFFISANTE:
        part_faible = sum(p for k, p in apt["classes"].items() if int(k) > CLASSE_SUFFISANTE)
        return "incertitude", (f"Parcelle hétérogène : classe {c} majoritaire mais {part_faible:.0%} "
                               f"de la surface en classe > {CLASSE_SUFFISANTE}")
    if c <= CLASSE_LIMITE:
        return "incertitude", f"Aptitude {CLASSES[c].lower()} (classe {c}), proche du seuil"
    return "non", f"Aptitude des terres insuffisante : {CLASSES[c].lower()} (classe {c})"


def analyser(geom, codes, irrigation):
    pixels = px.pixels_touches(geom, px.GAEZ)
    eau = scenario_eau(irrigation)
    with ThreadPoolExecutor(max_workers=8) as pool:
        resultats = list(pool.map(lambda c: aptitude_culture(c, pixels, eau), codes))
    return {r["code_gaez"]: r for r in resultats}, px.resume_pixels(geom, px.GAEZ, pixels), eau
