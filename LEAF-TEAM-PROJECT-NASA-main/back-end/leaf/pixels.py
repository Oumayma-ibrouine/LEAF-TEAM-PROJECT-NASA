"""
Le concept des pixels.

Chaque source de données est une grille : une valeur par pixel, jamais par parcelle.
Ce module répond, pour chaque source, à la question :
    « quels pixels la parcelle touche-t-elle, et quelle part de la parcelle tombe dans chacun ? »

    Source               Pixel                  ≈ taille au Maroc (34° N)
    FAO GAEZ v5          30" (1/120°)           0,77 × 0,93 km  (≈ 70 ha)
    GPM IMERG (pluie)    0,1°                   9 × 11 km
    NASA POWER (climat)  0,5° lat × 0,625° lon  52 × 55 km

Toutes les valeurs d'une parcelle sont donc des moyennes de pixels pondérées par la part de surface
de la parcelle dans chaque pixel. Une parcelle plus petite qu'un pixel reçoit la valeur de la zone entière.
"""
import math
from dataclasses import dataclass

from pyproj import Geod
from shapely.geometry import Point, box, shape
from shapely.geometry.base import BaseGeometry

GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class Grille:
    nom: str
    pas_lat: float          # hauteur d'un pixel (degrés)
    pas_lon: float          # largeur d'un pixel (degrés)
    bord_lat: float         # latitude d'un bord de pixel (n'importe lequel)
    bord_lon: float         # longitude d'un bord de pixel

    def indices(self, lat, lon):
        """Ligne / colonne du pixel qui contient le point."""
        return (math.floor((lat - self.bord_lat) / self.pas_lat),
                math.floor((lon - self.bord_lon) / self.pas_lon))

    def boite(self, i, j):
        sud = self.bord_lat + i * self.pas_lat
        ouest = self.bord_lon + j * self.pas_lon
        return box(ouest, sud, ouest + self.pas_lon, sud + self.pas_lat)

    def centre(self, i, j):
        return (round(self.bord_lat + (i + 0.5) * self.pas_lat, 6),
                round(self.bord_lon + (j + 0.5) * self.pas_lon, 6))


# NASA POWER (MERRA-2) : centres des pixels sur -90 + k*0.5 et -180 + k*0.625
NASA_POWER = Grille("NASA POWER", 0.5, 0.625, -90.25, -180.3125)
# GPM IMERG : bords des pixels sur les multiples de 0.1°
GPM_IMERG = Grille("GPM IMERG", 0.1, 0.1, -90.0, -180.0)
# FAO GAEZ v5 RES05 : bords sur les multiples de 1/120° depuis (-180, 90)
GAEZ = Grille("FAO GAEZ v5", 1 / 120, 1 / 120, 90.0, -180.0)

GRILLES = {"nasa_power": NASA_POWER, "gpm": GPM_IMERG, "gaez": GAEZ}


# ------------------------------------------------------------------ géométrie de la parcelle
def lire_parcelle(polygone=None, latitude=None, longitude=None) -> BaseGeometry:
    """
    polygone : géométrie GeoJSON (Polygon / MultiPolygon, coordonnées [lon, lat]).
    Sans polygone, la parcelle est réduite à son point GPS.
    """
    if polygone:
        geom = shape(polygone)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Polygone de parcelle invalide")
        return geom
    if latitude is None or longitude is None:
        raise ValueError("Il faut un polygone ou un point GPS")
    return Point(longitude, latitude)


def surface_ha(geom: BaseGeometry) -> float:
    if geom.geom_type == "Point":
        return 0.0
    aire, _ = GEOD.geometry_area_perimeter(geom)
    return round(abs(aire) / 10_000, 3)


def _aire_locale(geom, lat_ref):
    """Aire en degrés² corrigée de la latitude (suffisant pour des parts à l'échelle d'une parcelle)."""
    return geom.area * math.cos(math.radians(lat_ref))


def pixels_touches(geom: BaseGeometry, grille: Grille, max_pixels=400):
    """
    Liste des pixels de la grille touchés par la parcelle :
    [{"i", "j", "centre_lat", "centre_lon", "part"}] ; la somme des parts vaut 1.
    """
    if geom.geom_type == "Point":
        i, j = grille.indices(geom.y, geom.x)
        lat, lon = grille.centre(i, j)
        return [{"i": i, "j": j, "centre_lat": lat, "centre_lon": lon, "part": 1.0}]

    ouest, sud, est, nord = geom.bounds
    i0, j0 = grille.indices(sud, ouest)
    i1, j1 = grille.indices(nord, est)
    if (i1 - i0 + 1) * (j1 - j0 + 1) > max_pixels:
        raise ValueError(f"Parcelle trop grande pour la grille {grille.nom}")

    lat_ref = geom.centroid.y
    total = _aire_locale(geom, lat_ref)
    pixels = []
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            inter = geom.intersection(grille.boite(i, j))
            if inter.is_empty:
                continue
            part = _aire_locale(inter, lat_ref) / total if total else 0
            if part <= 1e-6:
                continue
            lat, lon = grille.centre(i, j)
            pixels.append({"i": i, "j": j, "centre_lat": lat, "centre_lon": lon, "part": part})

    somme = sum(p["part"] for p in pixels) or 1
    for p in pixels:
        p["part"] = round(p["part"] / somme, 4)
    return pixels


def taille_pixel_km(grille: Grille, latitude: float):
    """Dimensions approximatives d'un pixel à cette latitude."""
    h = grille.pas_lat * 111.32
    l = grille.pas_lon * 111.32 * math.cos(math.radians(latitude))
    return round(l, 2), round(h, 2)


def resume_pixels(geom: BaseGeometry, grille: Grille, pixels):
    lat = geom.centroid.y
    largeur, hauteur = taille_pixel_km(grille, lat)
    return {
        "source": grille.nom,
        "taille_pixel_km": {"largeur": largeur, "hauteur": hauteur},
        "surface_pixel_ha": round(largeur * hauteur * 100, 1),
        "nb_pixels": len(pixels),
        "pixels": pixels,
    }


def moyenne_ponderee(valeurs_parts):
    """[(valeur, part)] -> moyenne pondérée en ignorant les valeurs manquantes."""
    ok = [(v, p) for v, p in valeurs_parts if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not ok:
        return None
    total = sum(p for _, p in ok)
    return sum(v * p for v, p in ok) / total if total else None
