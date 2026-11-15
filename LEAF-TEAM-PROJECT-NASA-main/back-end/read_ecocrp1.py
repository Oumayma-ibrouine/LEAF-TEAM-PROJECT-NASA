
import pandas as pd

# Charger ECOCROP
df = pd.read_parquet("data/ecocrop/ecocrop.parquet")

# Codes GAEZ et genres/espèces à rechercher dans ECOCROP
# Les groupes sont conservés pour afficher leurs différentes espèces.
cultures = {
    "BCK": ("Sarrasin", ["Fagopyrum"]),
    "BRL": ("Orge", ["Hordeum"]),
    "CAB": ("Chou", ["Brassica oleracea"]),
    "CAR": ("Carotte", ["Daucus carota"]),
    "CHK": ("Pois chiche", ["Cicer arietinum"]),
    "COW": ("Niébé", ["Vigna unguiculata"]),
    "CSV": ("Manioc", ["Manihot esculenta"]),
    "FIML": ("Millet à doigts", ["Eleusine coracana"]),
    "FML": ("Millet des oiseaux", ["Setaria italica"]),
    "FONIO": ("Fonio", ["Digitaria exilis", "Digitaria iburua"]),
    "GRD": ("Arachide", ["Arachis hypogaea"]),
    "GRM": ("Haricot mungo", ["Vigna radiata"]),
    "MZE": ("Maïs grain", ["Zea mays"]),
    "MZS": ("Maïs ensilage", ["Zea mays"]),
    "OAT": ("Avoine", ["Avena sativa"]),
    "OKRA": ("Gombo", ["Abelmoschus esculentus"]),
    "ONI": ("Oignon", ["Allium cepa"]),
    "PEA": ("Pois", ["Pisum sativum"]),
    "PHB": ("Haricot commun", ["Phaseolus vulgaris"]),
    "PIG": ("Pois d'Angole", ["Cajanus cajan"]),
    "PML": ("Millet perlé", ["Cenchrus americanus", "Pennisetum glaucum"]),
    "RCD": ("Riz pluvial", ["Oryza sativa"]),
    "RCW": ("Riz humide", ["Oryza sativa"]),
    "RSD": ("Colza", ["Brassica napus"]),
    "RYE": ("Seigle", ["Secale cereale"]),
    "SES": ("Sésame", ["Sesamum indicum"]),
    "SFL": ("Tournesol", ["Helianthus annuus"]),
    "SOY": ("Soja", ["Glycine max"]),
    "SPO": ("Patate douce", ["Ipomoea batatas"]),
    "SRG": ("Sorgho", ["Sorghum bicolor"]),
    "SUB": ("Betterave sucrière", ["Beta vulgaris"]),
    "SUC": ("Canne à sucre", ["Saccharum"]),
    "TAROD": ("Taro sec", ["Colocasia esculenta"]),
    "TAROW": ("Taro humide", ["Colocasia esculenta"]),
    "TEF": ("Teff", ["Eragrostis tef"]),
    "TOM": ("Tomate", ["Solanum lycopersicum", "Lycopersicon esculentum"]),
    "WHE": ("Blé", ["Triticum"]),
    "WMEL": ("Pastèque", ["Citrullus lanatus"]),
    "WPO": ("Pomme de terre", ["Solanum tuberosum"]),
    "YAM": ("Igname", ["Dioscorea"]),
}

colonnes = [
    "scientificname",
    "topmn", "topmx",
    "ropmn", "ropmx",
    "gmin", "gmax"
]

resultats = []
absentes = []

for code, (nom, especes) in cultures.items():

    masque = pd.Series(False, index=df.index)

    for espece in especes:
        # Correspondance exacte ou espèces du même genre
        correspondance = (
            df["scientificname"].eq(espece)
            | df["scientificname"].str.startswith(
                espece + " ", na=False
            )
        )
        masque = masque | correspondance

    selection = df.loc[masque, colonnes]

    if selection.empty:
        absentes.append((code, nom))
        continue

    for _, ligne in selection.iterrows():
        resultats.append({
            "Code GAEZ": code,
            "Culture": nom,
            "Espèce": ligne["scientificname"],
            "Température optimale": f'{ligne["topmn"]}–{ligne["topmx"]} °C',
            "Précipitations optimales": f'{ligne["ropmn"]}–{ligne["ropmx"]} mm',
            "Cycle": f'{ligne["gmin"]}–{ligne["gmax"]} jours'
        })

tableau = pd.DataFrame(resultats)

# Afficher le tableau complet
print("\n=== CULTURES GAEZ / ECOCROP ===\n")
print(tableau.to_string(index=False))

# Afficher les cultures non trouvées
print("\n=== CULTURES SANS CORRESPONDANCE ===")
for code, nom in absentes:
    print(code, "-", nom)

# Exporter en CSV
tableau.to_csv(
    "cultures_gaez_ecocrop.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\nFichier créé : cultures_gaez_ecocrop.csv")
print("Codes GAEZ traités :", len(cultures))
print("Codes avec correspondance :", len(cultures) - len(absentes))
print("Nombre de lignes obtenues :", len(tableau))
