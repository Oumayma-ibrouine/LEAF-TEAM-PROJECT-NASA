"""
Moteur de décision (étapes 5, 6, 8, 9 du schéma).

Pour chaque culture de cultures.csv :
  1. Conditions climatiques compatibles ?  -> oui / non (écartée, justification climat) / incertitude (à vérifier)
  2. Si oui : aptitude des terres GAEZ suffisante ? -> retenue / écartée (justification sol) / à vérifier

« Incertitude » = IS proche du minimum, probabilité proche du seuil, ou données manquantes.
Tous les seuils ci-dessous sont PROVISOIRES (à valider par l'agronome).
"""
from pathlib import Path

import pandas as pd

from . import climat, gaez

CSV_CULTURES = Path(__file__).resolve().parent.parent / "data" / "cultures.csv"

P_NON = 0.30            # risque dans >= 30 % des années -> culture écartée
P_INCERTITUDE = 0.10    # risque dans 10-30 % des années -> à vérifier (probabilité proche du seuil)
MARGE_IS = 0.05         # IS à moins de 0,05 du minimum -> à vérifier

NOMS_IS = {"temperature": "température", "humidite": "humidité", "pluie": "pluie", "vent": "vent"}


def charger_cultures():
    df = pd.read_csv(CSV_CULTURES)
    return df.where(pd.notna(df), None).to_dict(orient="records")


def _risque(p, libelle, non, incert):
    """Classe une probabilité annuelle de risque."""
    texte = f"{libelle} {p:.0%} des années"
    if p >= P_NON:
        non.append(texte)
    elif p >= P_INCERTITUDE:
        incert.append(texte + " (proche du seuil)")


def decision_climat(culture, stats, pluie_annuelle, indices, irrigation):
    non, incert, notes = [], [], []

    if stats is None or stats.empty:
        return "incertitude", [], ["Saison incomplète dans les données climatiques"], notes
    n = len(stats)
    if n < 5:
        incert.append(f"Seulement {n} saisons complètes dans les données")
    if stats["manquants"].sum() > 0:
        incert.append("Jours sans donnée climatique dans la saison")

    # Température moyenne mensuelle hors des limites absolues (logique ECOCROP)
    t_min, t_max = culture["t_abs_min"], culture["t_abs_max"]
    if t_min is None or t_max is None:
        incert.append("Limites de température absentes de cultures.csv")
    else:
        _risque(float((stats["tmoy_mois_min"] < t_min).mean()),
                f"Mois trop froid (< {t_min:g} °C) :", non, incert)
        _risque(float((stats["tmoy_mois_max"] > t_max).mean()),
                f"Mois trop chaud (> {t_max:g} °C) :", non, incert)

    # Gel : température journalière minimale sous la température létale
    t_gel = culture["t_gel"]
    if t_gel is not None:
        _risque(float((stats["tmin_jour_min"] < t_gel).mean()),
                f"Gel létal (Tmin < {t_gel:g} °C) :", non, incert)

    # Eau
    p_min = culture["pluie_abs_min"]
    if irrigation:
        notes.append("Besoin en eau couvert par l'irrigation (disponibilité de l'eau à vérifier)")
    elif p_min is None:
        incert.append("Besoin en eau absent de cultures.csv")
    elif pluie_annuelle.empty:
        incert.append("Pluie annuelle indisponible")
    else:
        _risque(float((pluie_annuelle < p_min).mean()),
                f"Pluie annuelle insuffisante (< {p_min:g} mm) :", non, incert)
        p_max = culture["pluie_abs_max"]
        if p_max is not None:
            _risque(float((pluie_annuelle > p_max).mean()),
                    f"Pluie annuelle excessive (> {p_max:g} mm) :", non, incert)

    # Température moyenne de saison vs optimum : information seulement
    t_moy = float(stats["tmoy"].mean())
    if culture["t_opt_min"] is not None and not (culture["t_opt_min"] <= t_moy <= culture["t_opt_max"]):
        notes.append(f"Température moyenne de saison {t_moy:.1f} °C hors optimum "
                     f"({culture['t_opt_min']:g}-{culture['t_opt_max']:g} °C)")

    # Indices de stabilité vs IS minimum toléré
    for cle, nom in NOMS_IS.items():
        valeur, minimum = indices.get(cle), culture.get(f"is_min_{cle}")
        if minimum is None:
            continue
        if valeur is None:
            incert.append(f"IS {nom} indisponible")
        elif valeur < minimum - MARGE_IS:
            (incert if (cle == "pluie" and irrigation) else non).append(
                f"IS {nom} {valeur:.2f} < minimum {minimum:.2f}")
        elif valeur < minimum + MARGE_IS:
            incert.append(f"IS {nom} {valeur:.2f} proche du minimum {minimum:.2f}")

    statut = "non" if non else ("incertitude" if incert else "oui")
    return statut, non, incert, notes


def evaluer(climat_res, aptitudes, date_plantation, irrigation):
    df = climat_res["_df"]
    pluie_an = climat.pluie_annuelle(climat_res["_pluie_mois"])
    resultats = []
    for c in charger_cultures():
        cycle = int(c["cycle_jours"] or 120)
        stats = climat.stats_saison(df, date_plantation, cycle)
        statut_c, non, incert, notes = decision_climat(c, stats, pluie_an, climat_res["indices"], irrigation)
        apt = aptitudes.get(c["code_gaez"], {"statut": "donnees_manquantes"})
        statut_s, justif_s = gaez.decision_sol(apt)

        if statut_c == "non":
            final, etape, justification = "ecartee", "climat", non
        elif statut_c == "incertitude":
            final, etape, justification = "a_verifier", "climat", incert
        elif statut_s == "non":
            final, etape, justification = "ecartee", "sol", [justif_s]
        elif statut_s == "incertitude":
            final, etape, justification = "a_verifier", "sol", [justif_s]
        else:
            final, etape, justification = "retenue", None, [justif_s]

        resultats.append({
            "code_gaez": c["code_gaez"],
            "nom": c["nom"],
            "famille": c["famille"],
            "groupe": c["groupe"],
            "cycle_jours": cycle,
            "statut": final,
            "etape": etape,
            "justification": justification,
            "notes": notes + ([f"Sol : {justif_s}"] if etape == "climat" else []),
            "climat": {
                "statut": statut_c,
                "saisons": len(stats),
                "p_froid": _p(stats, "tmoy_mois_min", "<", c["t_abs_min"]),
                "p_chaud": _p(stats, "tmoy_mois_max", ">", c["t_abs_max"]),
                "p_gel": _p(stats, "tmin_jour_min", "<", c["t_gel"]),
                "p_sec": None if irrigation or c["pluie_abs_min"] is None or pluie_an.empty
                         else round(float((pluie_an < c["pluie_abs_min"]).mean()), 2),
                "tmoy_saison": round(float(stats["tmoy"].mean()), 1) if not stats.empty else None,
            },
            "sol": apt,
            "validation": c["statut_validation"],
        })
    return resultats


def _p(stats, col, op, seuil):
    if seuil is None or stats is None or stats.empty:
        return None
    s = stats[col] < seuil if op == "<" else stats[col] > seuil
    return round(float(s.mean()), 2)
