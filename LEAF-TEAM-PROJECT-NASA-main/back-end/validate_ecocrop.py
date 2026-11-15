import pandas as pd

# Charger les 92 lignes
df = pd.read_csv("cultures_gaez_ecocrop.csv")

# Ajouter les colonnes de validation
df["statut"] = "A_VERIFIER"
df["justification"] = ""

# Quelques correspondances simples à préparer
valides = {
    "BRL": ["Hordeum vulgare"],
    "CAR": ["Daucus carota"],
    "CHK": ["Cicer arietinum"],
    "OKRA": ["Abelmoschus esculentus"],
    "SOY": ["Glycine max"],
    "WPO": ["Solanum tuberosum"],
    "WHE": [
        "Triticum aestivum",
        "Triticum durum",
        "Triticum compactum",
        "Triticum dicoccon",
        "Triticum spelta"
    ]
}

# Marquer les correspondances candidates
for code, especes in valides.items():
    masque = (
        (df["Code GAEZ"] == code)
        & df["Espèce"].isin(especes)
    )

    df.loc[masque, "statut"] = "A_VERIFIER"
    df.loc[masque, "justification"] = (
        "Espèce candidate : vérifier la définition GAEZ"
    )

# Détecter les valeurs climatiques manquantes
colonnes_climatiques = [
    "Température optimale",
    "Précipitations optimales",
    "Cycle"
]

df["donnees_a_verifier"] = df[
    colonnes_climatiques
].astype(str).apply(
    lambda ligne: any(
        "<NA>" in valeur or "0–0 jours" in valeur
        for valeur in ligne
    ),
    axis=1
)

# Enregistrer sans modifier le CSV original
df.to_csv(
    "cultures_gaez_a_valider.csv",
    index=False,
    encoding="utf-8-sig"
)

print("Lignes à examiner :", len(df))
print("Codes GAEZ :", df["Code GAEZ"].nunique())
print(
    "Lignes avec données à vérifier :",
    df["donnees_a_verifier"].sum()
)
print("Fichier créé : cultures_gaez_a_valider.csv")