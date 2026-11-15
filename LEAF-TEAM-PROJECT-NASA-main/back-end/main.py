"""
LEAF API — un seul back-end pour tout le schéma.

Lancer (depuis back-end/) :
    uvicorn main:app --port 8000
Documentation : http://127.0.0.1:8000/docs
Pluie GPM : définir EE_PROJECT (projet Google Earth Engine) ; sinon repli automatique sur NASA POWER.
"""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from leaf import climat, decision, gaez, rapport, rotations
from leaf import pixels as px

app = FastAPI(title="LEAF API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "leaf.db"

# Variables locales (ex. ANTHROPIC_API_KEY) lues depuis back-end/.env si présent
_env = BASE_DIR / ".env"
if _env.exists():
    import os
    for _l in _env.read_text(encoding="utf-8-sig").splitlines():
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def connexion():
    return sqlite3.connect(DB)


with connexion() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS champs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
            surface REAL NOT NULL, date_plantation TEXT NOT NULL, culture TEXT, adresse TEXT)""")
    colonnes = [l[1] for l in conn.execute("PRAGMA table_info(champs)")]
    for nom, type_sql in [("culture", "TEXT"), ("adresse", "TEXT"), ("polygone", "TEXT"), ("irrigation", "INTEGER")]:
        if nom not in colonnes:
            conn.execute(f"ALTER TABLE champs ADD COLUMN {nom} {type_sql}")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, champ_id INTEGER, cree_le TEXT, entree TEXT, resultat TEXT)""")


# ------------------------------------------------------------------ modèles
class Champ(BaseModel):
    nom: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    surface: float = Field(gt=0)
    date_plantation: date
    culture: str | None = None
    adresse: str | None = None
    polygone: dict | None = None          # géométrie GeoJSON, coordonnées [lon, lat]
    irrigation: bool = False


class DemandeAnalyse(BaseModel):
    nom: str | None = None
    polygone: dict | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    date_plantation: date
    irrigation: bool = False
    champ_id: int | None = None


# ------------------------------------------------------------------ champs
@app.get("/")
def accueil():
    return {"message": "LEAF Backend fonctionne"}


@app.post("/champs")
def ajouter_champ(champ: Champ):
    with connexion() as conn:
        cur = conn.execute(
            """INSERT INTO champs (nom, latitude, longitude, surface, date_plantation, culture, adresse,
                                   polygone, irrigation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (champ.nom, champ.latitude, champ.longitude, champ.surface, champ.date_plantation.isoformat(),
             champ.culture, champ.adresse, json.dumps(champ.polygone) if champ.polygone else None,
             int(champ.irrigation)))
    return {"message": "Champ enregistré", "id": cur.lastrowid}


@app.get("/champs")
def afficher_champs():
    with connexion() as conn:
        conn.row_factory = sqlite3.Row
        lignes = conn.execute("SELECT * FROM champs").fetchall()
    resultat = []
    for l in lignes:
        d = dict(l)
        d["polygone"] = json.loads(d["polygone"]) if d.get("polygone") else None
        d["irrigation"] = bool(d.get("irrigation"))
        resultat.append(d)
    return resultat


# ------------------------------------------------------------------ pixels
@app.post("/pixels")
def pixels_parcelle(demande: DemandeAnalyse):
    """Pixels de chaque source touchés par la parcelle (pour les afficher sur la carte)."""
    geom = _geometrie(demande)
    sortie = {"surface_ha": px.surface_ha(geom)}
    for cle, grille in px.GRILLES.items():
        pix = px.pixels_touches(geom, grille)
        res = px.resume_pixels(geom, grille, pix)
        for p in res["pixels"]:
            b = grille.boite(p["i"], p["j"]).bounds
            p["bbox"] = [b[1], b[0], b[3], b[2]]          # [sud, ouest, nord, est] pour Leaflet
        sortie[cle] = res
    return sortie


# ------------------------------------------------------------------ analyse complète
def _geometrie(demande):
    try:
        return px.lire_parcelle(demande.polygone, demande.latitude, demande.longitude)
    except ValueError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur)) from erreur


def _calculer(demande: DemandeAnalyse):
    geom = _geometrie(demande)
    codes = [c["code_gaez"] for c in decision.charger_cultures()]

    # Climat (NASA POWER / GPM) et sol (GAEZ) en parallèle
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_climat = pool.submit(climat.analyser, geom)
        f_gaez = pool.submit(gaez.analyser, geom, codes, demande.irrigation)
        try:
            clim = f_climat.result()
        except Exception as erreur:
            raise HTTPException(status_code=502, detail=f"Données climatiques indisponibles : {erreur}") from erreur
        aptitudes, pixels_gaez, scenario = f_gaez.result()

    cultures = decision.evaluer(clim, aptitudes, demande.date_plantation, demande.irrigation)
    especes = {c["code_gaez"]: c["espece_reference"] for c in decision.charger_cultures()}
    rot = rotations.construire(cultures, especes)
    cycle_ref = 120
    centre = geom.centroid

    analyse = {
        "parcelle": {
            "nom": demande.nom, "surface_ha": px.surface_ha(geom),
            "centre_lat": centre.y, "centre_lon": centre.x,
            "date_plantation": demande.date_plantation.isoformat(), "irrigation": demande.irrigation,
            "scenario_gaez": scenario,
        },
        "pixels": {"gaez": pixels_gaez, **clim["pixels"]},
        "climat": {
            "periode": clim["periode"], "indices": clim["indices"],
            "source_pluie": clim["details"]["pluie"]["source"],
            "pluie_annuelle_moyenne_mm": clim["details"]["pluie"]["pluie_annuelle_moyenne_mm"],
            "is_par_mois": {"temperature": clim["details"]["temperature"]["is_par_mois"],
                            "humidite": clim["details"]["humidite"]["is_par_mois"],
                            "vent": clim["details"]["vent"]["is_par_mois"]},
        },
        "saison": climat.normales_saison(clim["_df"], demande.date_plantation, cycle_ref),
        "cultures": cultures,
        "resume": {s: sum(c["statut"] == s for c in cultures) for s in ("retenue", "a_verifier", "ecartee")},
        "rotations": rot,
        "avertissement": "Seuils provisoires à valider par l'agronome. Décision finale : agriculteur + technicien.",
    }
    return analyse, clim


@app.post("/analyse")
def lancer_analyse(demande: DemandeAnalyse):
    analyse, _ = _calculer(demande)
    with connexion() as conn:
        cur = conn.execute("INSERT INTO analyses (champ_id, cree_le, entree, resultat) VALUES (?, ?, ?, ?)",
                           (demande.champ_id, datetime.now().isoformat(timespec="seconds"),
                            demande.model_dump_json(), json.dumps(analyse, ensure_ascii=False)))
    analyse["id"] = cur.lastrowid
    analyse["rapport_pdf"] = f"/analyses/{cur.lastrowid}/rapport.pdf"
    return analyse


def _lire_analyse(analyse_id):
    with connexion() as conn:
        ligne = conn.execute("SELECT entree, resultat FROM analyses WHERE id = ?", (analyse_id,)).fetchone()
    if not ligne:
        raise HTTPException(status_code=404, detail="Analyse introuvable")
    return DemandeAnalyse.model_validate_json(ligne[0]), json.loads(ligne[1])


@app.get("/analyses/{analyse_id}")
def obtenir_analyse(analyse_id: int):
    return _lire_analyse(analyse_id)[1]


@app.get("/analyses/{analyse_id}/rapport.pdf")
def rapport_pdf(analyse_id: int):
    demande, analyse = _lire_analyse(analyse_id)
    clim = climat.analyser(_geometrie(demande))          # relu depuis le cache des pixels : rapide
    pdf = rapport.generer(analyse, clim["_df"], clim["details"])
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="rapport_leaf_{analyse_id}.pdf"'})


# ------------------------------------------------------------------ santé des plantes (IA)
class DemandePlante(BaseModel):
    image: str                              # base64 (ou data URL)
    media_type: str = "image/jpeg"
    culture: str | None = None
    symptomes: str | None = None
    parcelle: str | None = None
    langue: str = "fr"


@app.post("/plante/analyse")
def analyse_plante(demande: DemandePlante):
    from leaf import plante
    import anthropic
    try:
        return plante.analyser(demande.image, demande.media_type, demande.culture,
                               demande.symptomes, demande.parcelle, demande.langue)
    except plante.CleAbsente as erreur:
        raise HTTPException(status_code=503, detail=str(erreur)) from erreur
    except ValueError as erreur:
        raise HTTPException(status_code=422, detail=str(erreur)) from erreur
    except anthropic.AuthenticationError as erreur:
        raise HTTPException(status_code=503, detail="Clé API Anthropic invalide ou absente "
                                                    "(définir ANTHROPIC_API_KEY).") from erreur
    except anthropic.RateLimitError as erreur:
        raise HTTPException(status_code=429, detail="Trop de demandes à l'IA, réessayez dans un instant.") from erreur
    except anthropic.APIStatusError as erreur:
        raise HTTPException(status_code=502, detail=f"Erreur de l'IA : {erreur.message}") from erreur
    except anthropic.APIConnectionError as erreur:
        raise HTTPException(status_code=502, detail="Impossible de joindre l'API Anthropic.") from erreur
    except TypeError as erreur:                 # aucune clé configurée
        raise HTTPException(status_code=503, detail="Clé API Anthropic absente (définir ANTHROPIC_API_KEY).") from erreur
    except RuntimeError as erreur:
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur


# ------------------------------------------------------------------ compatibilité ancien front
@app.get("/gaez/suitability")
def gaez_suitability(latitude: float, longitude: float, culture: str = "WHE", irrigation: bool = True):
    geom = px.lire_parcelle(latitude=latitude, longitude=longitude)
    res, _, eau = gaez.analyser(geom, [culture], irrigation)
    r = res[culture]
    if r.get("statut") != "ok":
        raise HTTPException(status_code=404, detail="Aucune donnée GAEZ disponible")
    return {"culture": culture, "latitude": latitude, "longitude": longitude, "classe": r["classe_majoritaire"],
            "aptitude": r["aptitude"], "scenario": eau, "periode": "2001-2020", "source": "FAO GAEZ v5"}
