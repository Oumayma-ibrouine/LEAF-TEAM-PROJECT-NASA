import pandas as pd

# Charger le dataset ECOCROP
df = pd.read_parquet("data/ecocrop/ecocrop.parquet")

# Afficher les colonnes disponibles
print("=== COLONNES ECOCROP ===")
print(df.columns.tolist())

# Afficher le nombre de cultures
print("\nNombre de lignes :", len(df))

# Afficher les premières lignes
print("\n=== EXEMPLE DE DONNÉES ===")
print(df.head(5).to_string(index=False))