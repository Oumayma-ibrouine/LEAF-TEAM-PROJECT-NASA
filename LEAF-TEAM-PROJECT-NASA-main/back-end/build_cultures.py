"""
Construit data/cultures.csv : la table de référence des 40 cultures (étape 5 du schéma).

Source des seuils : FAO ECOCROP (data/ecocrop/ecocrop.parquet), une espèce de référence par code GAEZ.
TOUTES les valeurs sont PROVISOIRES tant que l'agronome ne les a pas validées
(colonne statut_validation). L'agronome peut corriger directement le CSV : l'API le relit à chaque analyse.

Lancer :  python build_cultures.py
"""
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
SORTIE = BASE / "data" / "cultures.csv"

# code GAEZ -> (nom, espèce ECOCROP de référence, groupe agronomique)
CULTURES = {
    "WHE": ("Blé", "Triticum aestivum", "cereale"),
    "BRL": ("Orge", "Hordeum vulgare", "cereale"),
    "MZE": ("Maïs grain", "Zea mays", "cereale"),
    "MZS": ("Maïs ensilage", "Zea mays", "cereale"),
    "SRG": ("Sorgho", "Sorghum bicolor", "cereale"),
    "OAT": ("Avoine", "Avena sativa", "cereale"),
    "RYE": ("Seigle", "Secale cereale", "cereale"),
    "PML": ("Millet perlé", "Pennisetum glaucum", "cereale"),
    "FML": ("Millet des oiseaux", "Setaria italica", "cereale"),
    "FIML": ("Millet à doigts", "Eleusine coracana", "cereale"),
    "FONIO": ("Fonio", "Digitaria exilis", "cereale"),
    "TEF": ("Teff", "Eragrostis tef", "cereale"),
    "RCW": ("Riz humide", "Oryza sativa", "cereale"),
    "RCD": ("Riz pluvial", "Oryza sativa", "cereale"),
    "BCK": ("Sarrasin", "Fagopyrum esculentum", "pseudo-cereale"),
    "CHK": ("Pois chiche", "Cicer arietinum", "legumineuse"),
    "COW": ("Niébé", "Vigna unguiculata", "legumineuse"),
    "PEA": ("Pois", "Pisum sativum", "legumineuse"),
    "PHB": ("Haricot commun", "Phaseolus vulgaris", "legumineuse"),
    "PIG": ("Pois d'Angole", "Cajanus cajan", "legumineuse"),
    "GRM": ("Haricot mungo", "Vigna radiata", "legumineuse"),
    "SOY": ("Soja", "Glycine max", "legumineuse"),
    "GRD": ("Arachide", "Arachis hypogaea", "legumineuse"),
    "TOM": ("Tomate", "Lycopersicon esculentum", "legume"),
    "ONI": ("Oignon", "Allium cepa", "legume"),
    "CAR": ("Carotte", "Daucus carota", "legume"),
    "CAB": ("Chou", "Brassica oleracea", "legume"),
    "OKRA": ("Gombo", "Abelmoschus esculentus", "legume"),
    "WMEL": ("Pastèque", "Citrullus lanatus", "legume"),
    "WPO": ("Pomme de terre", "Solanum tuberosum", "tubercule"),
    "SPO": ("Patate douce", "Ipomoea batatas", "tubercule"),
    "CSV": ("Manioc", "Manihot esculenta", "tubercule"),
    "YAM": ("Igname", "Dioscorea rotundata", "tubercule"),
    "TAROD": ("Taro (sec)", "Colocasia esculenta", "tubercule"),
    "TAROW": ("Taro (humide)", "Colocasia esculenta", "tubercule"),
    "SES": ("Sésame", "Sesamum indicum", "oleagineux"),
    "SFL": ("Tournesol", "Helianthus annuus", "oleagineux"),
    "RSD": ("Colza", "Brassica napus", "oleagineux"),
    "SUB": ("Betterave sucrière", "Beta vulgaris", "sucriere"),
    "SUC": ("Canne à sucre", "Saccharum officinarum", "sucriere"),
}

# Familles botaniques (nom actuel APG) : ECOCROP utilise parfois d'anciens noms (Gramineae, Leguminosae...)
FAMILLES = {
    "Gramineae": "Poaceae", "Leguminosae": "Fabaceae", "Cruciferae": "Brassicaceae",
    "Compositae": "Asteraceae", "Umbelliferae": "Apiaceae", "Chenopodiaceae": "Amaranthaceae",
    "Alliaceae": "Amaryllidaceae",
}

# Valeurs par défaut PROVISOIRES (à remplacer par l'agronome)
IS_MIN_DEFAUT = 0.5
CYCLE_DEFAUT = {"WMEL": 95}          # ECOCROP indique 0-0 jours pour la pastèque


def trouver(df, espece):
    exact = df[df["scientificname"] == espece]
    if not exact.empty:
        return exact.iloc[0]
    proche = df[df["scientificname"].str.startswith(espece, na=False)]
    return proche.iloc[0] if not proche.empty else None


def nombre(valeur):
    return None if pd.isna(valeur) else float(valeur)


def main():
    df = pd.read_parquet(BASE / "data" / "ecocrop" / "ecocrop.parquet")
    lignes = []
    for code, (nom, espece, groupe) in CULTURES.items():
        e = trouver(df, espece)
        notes = []
        if e is None:
            notes.append(f"{espece} absente d'ECOCROP : tous les seuils à saisir")
            e = pd.Series(dtype=object)
        famille_brute = str(e.get("famname", "") or "").split(":")[-1]
        famille = FAMILLES.get(famille_brute, famille_brute) or None

        gmin, gmax = nombre(e.get("gmin")), nombre(e.get("gmax"))
        if code in CYCLE_DEFAUT or not gmin or not gmax:
            cycle = CYCLE_DEFAUT.get(code)
            notes.append("cycle absent d'ECOCROP : valeur par défaut")
        else:
            cycle = round((gmin + gmax) / 2)

        # Température létale : la plus basse entre croissance (ktmp) et repos/endurcie (ktmpr)
        letales = [v for v in (nombre(e.get("ktmp")), nombre(e.get("ktmpr"))) if v is not None]
        t_gel = min(letales) if letales else None
        if t_gel is None:
            t_gel = 0.0
            notes.append("température létale absente : 0 °C par défaut")

        lignes.append({
            "code_gaez": code,
            "nom": nom,
            "espece_reference": e.get("scientificname", espece),
            "famille": famille,
            "groupe": groupe,
            "cycle_jours": cycle,
            "t_opt_min": nombre(e.get("topmn")),
            "t_opt_max": nombre(e.get("topmx")),
            "t_abs_min": nombre(e.get("tmin")),
            "t_abs_max": nombre(e.get("tmax")),
            "t_gel": t_gel,
            "pluie_opt_min": nombre(e.get("ropmn")),
            "pluie_opt_max": nombre(e.get("ropmx")),
            "pluie_abs_min": nombre(e.get("rmin")),
            "pluie_abs_max": nombre(e.get("rmax")),
            "is_min_temperature": IS_MIN_DEFAUT,
            "is_min_humidite": IS_MIN_DEFAUT,
            "is_min_pluie": IS_MIN_DEFAUT,
            "is_min_vent": IS_MIN_DEFAUT,
            "source": "FAO ECOCROP + FAO GAEZ v5",
            "statut_validation": "PROVISOIRE - a valider par l'agronome",
            "notes": " ; ".join(notes),
        })

    tableau = pd.DataFrame(lignes)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    tableau.to_csv(SORTIE, index=False, encoding="utf-8")
    print(f"{len(tableau)} cultures écrites dans {SORTIE}")
    manquants = tableau[tableau["notes"] != ""][["code_gaez", "notes"]]
    if not manquants.empty:
        print("\nÀ compléter par l'agronome :")
        print(manquants.to_string(index=False))


if __name__ == "__main__":
    main()
