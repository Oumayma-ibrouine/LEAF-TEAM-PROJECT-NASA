"""
Construction et comparaison des rotations (étapes 10-11 du schéma).

Règles :
  - une culture par an, rotation cyclique de 3 ans (l'année 4 revient à la culture 1) ;
  - au moins une céréale et au moins une légumineuse ; une légumineuse précède une céréale
    (alternance céréale <-> légumineuse : la légumineuse laisse de l'azote à la céréale) ;
  - jamais deux fois de suite la même famille botanique, y compris entre la dernière et la première année ;
  - une même espèce n'apparaît qu'une fois (ex. maïs grain et maïs ensilage).
Seules les cultures « retenues » entrent dans les rotations.
"""
from itertools import permutations

CEREALES = {"cereale"}
LEGUMINEUSES = {"legumineuse"}
LONGUEUR = 3


def _valide(seq):
    n = len(seq)
    familles = [c["famille"] for c in seq]
    if any(familles[k] == familles[(k + 1) % n] for k in range(n)):
        return False
    if len({c["espece"] for c in seq}) < n:
        return False
    groupes = [c["groupe"] for c in seq]
    if not any(g in CEREALES for g in groupes) or not any(g in LEGUMINEUSES for g in groupes):
        return False
    return any(groupes[k] in LEGUMINEUSES and groupes[(k + 1) % n] in CEREALES for k in range(n))


def _canonique(seq):
    """Une rotation cyclique n'a qu'une forme : on la fait commencer par une céréale, la plus petite."""
    codes = [c["code_gaez"] for c in seq]
    rotations = [codes[k:] + codes[:k] for k in range(len(codes))]
    return min(rotations)


def _score(c):
    """Plus c'est haut, mieux c'est : bonne classe GAEZ et faible risque climatique."""
    sol = c["sol"].get("classe_moyenne") or 8
    risques = [v for k, v in c["climat"].items() if k.startswith("p_") and v is not None]
    return (8 - sol) / 7 - max(risques, default=0)


def _manque(cultures):
    if not any(c["groupe"] in CEREALES for c in cultures):
        return "céréale"
    if not any(c["groupe"] in LEGUMINEUSES for c in cultures):
        return "légumineuse"
    return None


def construire(cultures_evaluees, especes):
    """Rotations à partir des cultures retenues ; à défaut, rotations provisoires incluant les « à vérifier »."""
    def avec_espece(statuts):
        return [dict(c, espece=especes.get(c["code_gaez"], c["code_gaez"]))
                for c in cultures_evaluees if c["statut"] in statuts]

    retenues = avec_espece({"retenue"})
    manque_ret = _manque(retenues)
    if not manque_ret:
        fiches = _rotations(retenues)
        if fiches:
            for f in fiches:
                del f["_seq"]
                f["provisoire"] = False
            return {"rotations": fiches, "provisoire": False, "message": None}

    # Repli : les cultures « à vérifier » complètent les retenues (rotation provisoire)
    elargies = avec_espece({"retenue", "a_verifier"})
    manque = _manque(elargies)
    if manque:
        return {"rotations": [], "provisoire": False,
                "message": f"Aucune rotation possible : pas de {manque} retenue ni à vérifier sur cette parcelle."}
    fiches = _rotations(elargies)
    if not fiches:
        return {"rotations": [], "provisoire": False,
                "message": "Aucune rotation possible : pas assez de familles botaniques différentes "
                           "(il faut 3 familles dont une céréale et une légumineuse)."}
    for f in fiches:
        douteuses = [s["nom"] for s, c in zip(f["sequence"], f["_seq"]) if c["statut"] == "a_verifier"]
        f["provisoire"] = bool(douteuses)
        if douteuses:
            f["risques"].insert(0, f"Rotation provisoire : {', '.join(douteuses)} à vérifier avant semis")
    raison = (f"pas de {manque_ret} retenue" if manque_ret
              else "pas assez de familles botaniques parmi les cultures retenues")
    for f in fiches:
        del f["_seq"]
    return {"rotations": fiches, "provisoire": True,
            "message": f"Rotations provisoires ({raison}) : elles incluent des cultures à vérifier."}


def _rotations(cultures):
    # Limiter la combinatoire : les 12 meilleures cultures
    retenues = sorted(cultures, key=_score, reverse=True)[:12]
    vues, candidates = set(), []
    for seq in permutations(retenues, LONGUEUR):
        if not _valide(seq):
            continue
        cle = tuple(_canonique(seq))
        if cle in vues:
            continue
        vues.add(cle)
        candidates.append((sum(_score(c) for c in seq) / LONGUEUR, seq))

    candidates.sort(key=lambda x: x[0], reverse=True)
    choisies, utilisees = [], []
    for score, seq in candidates:              # 3 rotations les plus différentes possible
        codes = {c["code_gaez"] for c in seq}
        if all(len(codes & u) <= 1 for u in utilisees) or len(candidates) <= 3:
            choisies.append((score, seq))
            utilisees.append(codes)
        if len(choisies) == 3:
            break
    for score, seq in candidates:              # compléter si pas assez de rotations très différentes
        if len(choisies) == 3:
            break
        if all(seq is not s for _, s in choisies):
            choisies.append((score, seq))

    fiches = []
    for k, (score, seq) in enumerate(choisies):
        f = _fiche(k + 1, score, seq)
        f["_seq"] = seq
        fiches.append(f)
    return fiches


def _fiche(numero, score, seq):
    noms = [c["nom"] for c in seq]
    legs = [c for c in seq if c["groupe"] in LEGUMINEUSES]
    cers = [c for c in seq if c["groupe"] in CEREALES]
    familles = sorted({c["famille"] for c in seq})

    preuves = []
    for c in seq:
        cl = c["climat"]
        risques = ", ".join(f"{k[2:]} {v:.0%}" for k, v in cl.items() if k.startswith("p_") and v)
        preuves.append(f"{c['nom']} : GAEZ classe {c['sol'].get('classe_majoritaire')} "
                       f"({c['sol'].get('aptitude', '?')}), T° saison {cl.get('tmoy_saison')} °C"
                       + (f", risques {risques}" if risques else ", aucun risque climatique détecté"))

    risques = []
    for c in seq:
        cl = c["climat"]
        pmax = max((v for k, v in cl.items() if k.startswith("p_") and v is not None), default=0)
        if pmax > 0:
            risques.append(f"{c['nom']} : un risque climatique survient {pmax:.0%} des années")
        if c["sol"].get("heterogene"):
            risques.append(f"{c['nom']} : parcelle hétérogène sur les pixels GAEZ")

    return {
        "numero": numero,
        "sequence": [{"annee": k + 1, "code_gaez": c["code_gaez"], "nom": c["nom"], "famille": c["famille"],
                      "groupe": c["groupe"]} for k, c in enumerate(seq)],
        "titre": " → ".join(noms) + f" → {noms[0]}",
        "score": round(score, 3),
        "pourquoi": (f"Alterne {', '.join(c['nom'] for c in cers)} (céréale) et "
                     f"{', '.join(c['nom'] for c in legs)} (légumineuse), sur {len(familles)} familles "
                     f"botaniques différentes, avec les meilleures aptitudes GAEZ parmi les cultures retenues."),
        "preuves": preuves,
        "benefices": [
            f"Fixation d'azote par {', '.join(c['nom'] for c in legs)} : moins d'engrais azoté pour la céréale suivante",
            f"{len(familles)} familles ({', '.join(familles)}) : rupture des cycles de maladies et ravageurs",
            "Diversification des revenus et étalement des risques sur 3 ans",
        ],
        "lacunes": [
            "Seuils de cultures.csv provisoires (ECOCROP), non encore validés par l'agronome",
            "Une seule date de plantation appliquée à toutes les cultures",
            "Pas de données de marché, de rendement ni de main-d'œuvre",
            "Climat : pixels de 50 km (NASA POWER) ; sol : pixels d'environ 1 km (GAEZ)",
        ],
        "risques": risques or ["Aucun risque majeur détecté dans les données"],
    }
