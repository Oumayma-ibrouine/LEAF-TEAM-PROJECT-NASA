"""
Analyse d'une photo de plante par une IA de vision.

Fournisseurs (back-end/.env) :
  - Google Gemini, offre gratuite : GEMINI_API_KEY (https://aistudio.google.com/apikey) — par défaut ;
  - Claude (Anthropic, payant) : ANTHROPIC_API_KEY.
IA_FOURNISSEUR=gemini|claude force le choix.
"""
import base64
import json
import os
import time

import anthropic
import requests
from pydantic import BaseModel, Field

MODELE = "claude-opus-5-5"
TYPES_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
TAILLE_MAX = 5 * 1024 * 1024          # limite de l'API pour une image en base64

SYSTEME = """Tu es un agronome qui aide des agriculteurs (Maroc / Afrique du Nord) à inspecter leurs cultures.
On te donne une photo prise au champ, éventuellement la culture et les symptômes observés.

- Décris d'abord ce que la photo montre réellement. Si ce n'est pas une plante (ou si la plante n'est pas
  identifiable : photo floue, trop loin, autre objet), dis-le simplement dans `est_une_plante` / `observation`
  et ne propose pas de diagnostic inventé.
- Propose au plus 3 hypothèses (maladie, ravageur, carence, stress hydrique ou thermique, ou « plante saine »),
  de la plus probable à la moins probable, avec les indices visibles qui les appuient.
- La confiance doit refléter ce qu'une photo permet vraiment de dire : un diagnostic certain sur photo est rare.
- Les actions sont concrètes et prudentes : vérifications à faire au champ d'abord, puis mesures de gestion.
  Ne donne pas de dose de produit phytosanitaire ; renvoie vers un technicien pour tout traitement chimique.
- Réponds dans la langue demandée."""


class Hypothese(BaseModel):
    nom: str = Field(description="Nom de la maladie, du ravageur, de la carence ou du stress")
    type: str = Field(description="maladie | ravageur | carence | stress | sain | autre")
    confiance: str = Field(description="faible | moyenne | elevee")
    indices: list[str] = Field(description="Signes visibles sur la photo qui appuient l'hypothèse")


class Diagnostic(BaseModel):
    est_une_plante: bool
    plante_identifiee: str = Field(description="Espèce ou organe vu (ex. « feuille de blé »), ou « inconnue »")
    observation: str = Field(description="Ce que la photo montre, en 1 à 3 phrases")
    etat_general: str = Field(description="sain | suspect | atteint | indetermine")
    hypotheses: list[Hypothese]
    actions: list[str] = Field(description="Vérifications et mesures recommandées, dans l'ordre")
    quand_appeler_technicien: str
    qualite_photo: str = Field(description="Conseil pour une meilleure photo si besoin, sinon « correcte »")


LANGUES = {"fr": "français", "en": "English", "ar": "العربية"}
_client = None


def _client_api():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def analyser(image_b64: str, media_type: str, culture: str | None = None,
             symptomes: str | None = None, parcelle: str | None = None, langue: str = "fr") -> dict:
    if media_type not in TYPES_IMAGE:
        raise ValueError(f"Format d'image non pris en charge : {media_type}")
    if "," in image_b64[:100]:                       # data URL « data:image/jpeg;base64,... »
        image_b64 = image_b64.split(",", 1)[1]
    if len(base64.b64decode(image_b64, validate=False)) > TAILLE_MAX:
        raise ValueError("Image trop lourde (5 Mo maximum).")

    contexte = [f"Langue de la réponse : {LANGUES.get(langue, 'français')}."]
    if parcelle:
        contexte.append(f"Parcelle : {parcelle}.")
    contexte.append(f"Culture déclarée : {culture}." if culture else "Culture non précisée.")
    contexte.append(f"Symptômes observés par l'agriculteur : {symptomes}" if symptomes
                    else "Aucun symptôme décrit.")
    texte = "\n".join(contexte) + "\nAnalyse cette photo."

    if fournisseur() == "gemini":
        return _gemini(image_b64, media_type, texte)
    return _claude(image_b64, media_type, texte)


class CleAbsente(Exception):
    """Aucune clé d'API IA configurée."""


def fournisseur():
    """IA_FOURNISSEUR=gemini|claude dans .env ; sinon selon la clé présente (Gemini en priorité, gratuit)."""
    choix = os.environ.get("IA_FOURNISSEUR", "").strip().lower()
    if choix in ("gemini", "claude"):
        return choix
    if _cle_valide("GEMINI_API_KEY"):
        return "gemini"
    if _cle_valide("ANTHROPIC_API_KEY"):
        return "claude"
    raise CleAbsente("Aucune clé IA configurée : ajoutez GEMINI_API_KEY (gratuite, https://aistudio.google.com/apikey) "
                     "dans back-end/.env puis redémarrez l'API.")


def _cle_valide(nom):
    v = os.environ.get(nom, "").strip()
    return bool(v) and v not in ("TA_CLE", "sk-ant-...", "VOTRE_CLE") and len(v) > 20


# ------------------------------------------------------------------ Google Gemini (offre gratuite)
GEMINI_MODELE = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")   # rapide et gratuit
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"


def _gemini(image_b64, media_type, texte):
    if not _cle_valide("GEMINI_API_KEY"):
        raise CleAbsente("GEMINI_API_KEY absente ou invalide dans back-end/.env "
                         "(clé gratuite : https://aistudio.google.com/apikey).")
    schema = json.dumps(Diagnostic.model_json_schema(), ensure_ascii=False)
    corps = {
        "systemInstruction": {"parts": [{"text": SYSTEME + "\n\nRéponds uniquement en JSON conforme à ce schéma :\n"
                                         + schema}]},
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": media_type, "data": image_b64}},
            {"text": texte},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    # Modèle principal puis modèles gratuits de secours (surcharge 503, quota 429, modèle retiré 404)
    modeles = list(dict.fromkeys([GEMINI_MODELE, "gemini-flash-latest", "gemini-flash-lite-latest"]))
    r, derniere = None, ""
    for modele in modeles:
        for essai in range(2):
            try:
                r = requests.post(GEMINI_URL.format(modele), json=corps, timeout=(10, 45),
                                  headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()})
            except requests.Timeout:
                r, derniere = None, f"{modele} : délai dépassé"
                break                                   # modèle trop lent : passer au suivant
            except requests.RequestException as erreur:
                raise RuntimeError(f"Impossible de joindre Gemini : {erreur}") from erreur
            if r.status_code in (400, 401, 403) and "API key" in r.text:
                raise CleAbsente("Clé Gemini refusée par Google : vérifiez GEMINI_API_KEY dans back-end/.env.")
            if r.ok:
                break
            derniere = f"{modele} : {r.status_code}"
            if r.status_code in (500, 503) and essai == 0:
                time.sleep(2)
                continue
            break
        if r is None:
            continue
        if r.ok:
            break
        if r.status_code not in (404, 429, 500, 503):
            raise RuntimeError(f"Erreur Gemini {r.status_code} : {r.text[:300]}")
    if r is None or not r.ok:
        if r is not None and r.status_code == 429:
            raise RuntimeError("Quota gratuit Gemini atteint, réessayez dans une minute.")
        raise RuntimeError(f"Gemini est surchargé pour le moment ({derniere}), réessayez dans quelques instants.")

    data = r.json()
    try:
        brut = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as erreur:
        raison = (data.get("promptFeedback") or {}).get("blockReason") or data.get("candidates", [{}])[0].get("finishReason")
        raise RuntimeError(f"Gemini n'a pas renvoyé d'analyse ({raison}).") from erreur
    brut = brut.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        diag = Diagnostic.model_validate_json(brut)
    except ValueError as erreur:
        raise RuntimeError("Réponse Gemini illisible, réessayez.") from erreur
    return {**diag.model_dump(), "modele": data.get("modelVersion", GEMINI_MODELE)}


# ------------------------------------------------------------------ Claude (Anthropic, payant)
def _claude(image_b64, media_type, texte):
    if not _cle_valide("ANTHROPIC_API_KEY"):
        raise CleAbsente("ANTHROPIC_API_KEY absente ou invalide dans back-end/.env.")
    reponse = _client_api().beta.messages.parse(
        model=MODELE,
        max_tokens=16000,
        system=SYSTEME,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": texte},
            ],
        }],
        output_format=Diagnostic,
    )
    if reponse.stop_reason == "refusal":
        raise RuntimeError("L'IA a refusé d'analyser cette image.")
    if reponse.parsed_output is None:
        raise RuntimeError(f"Réponse IA incomplète (arrêt : {reponse.stop_reason}).")
    return {**reponse.parsed_output.model_dump(), "modele": reponse.model}
