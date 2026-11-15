
from pathlib import Path
from urllib.parse import quote
import json
import requests

# ==========================================
# CONFIGURATION GAEZ V5
# ==========================================

BUCKET = "fao-gismgr-gaez-v5-data"

PREFIX = "DATA/GAEZ-V5/MAPSET/RES05-SIX30AS/"

SCENARIO = "HP0120.AGERA5.HIST"
WATER_INPUT = "HILM"

BASE_DIR = Path(__file__).resolve().parent
DEST = BASE_DIR / "data" / "gaez"

DEST.mkdir(parents=True, exist_ok=True)

session = requests.Session()

# ==========================================
# CULTURES ALIMENTAIRES SELECTIONNEES
# ==========================================

CULTURES = {
    # Cereales
    "WHE": "Ble",
    "BRL": "Orge",
    "MZE": "Mais",
    "MZS": "Mais - variante",
    "SRG": "Sorgho",
    "OAT": "Avoine",
    "RYE": "Seigle",
    "BCK": "Sarrasin",
    "PML": "Mil",
    "FML": "Millet",
    "FIML": "Millet a doigts",
    "FONIO": "Fonio",
    "TEF": "Teff",
    "RCW": "Riz",
    "RCD": "Riz - variante",

    # Legumineuses
    "CHK": "Pois chiche",
    "COW": "Niebe",
    "PEA": "Pois",
    "PHB": "Haricot",
    "PIG": "Pois d'Angole",
    "GRM": "Gram",
    "SOY": "Soja",
    "GRD": "Arachide",

    # Legumes
    "TOM": "Tomate",
    "ONI": "Oignon",
    "CAR": "Carotte",
    "CAB": "Chou",
    "OKRA": "Gombo",
    "WMEL": "Pasteque",

    # Tubercules
    "WPO": "Pomme de terre",
    "SPO": "Patate douce",
    "CSV": "Manioc",
    "YAM": "Igname",
    "TAROD": "Taro - variante",
    "TAROW": "Taro - variante",

    # Oleagineux et cultures sucrieres
    "SES": "Sesame",
    "SFL": "Tournesol",
    "RSD": "Colza",
    "SUB": "Betterave sucriere",
    "SUC": "Canne a sucre"
}


# ==========================================
# 1. RECUPERER LE CATALOGUE
# ==========================================

def list_objects():
    url = (
        f"https://storage.googleapis.com/"
        f"storage/v1/b/{BUCKET}/o"
    )

    token = None

    while True:
        params = {
            "prefix": PREFIX,
            "maxResults": 1000,
            "fields": "nextPageToken,items(name,size)"
        }

        if token:
            params["pageToken"] = token

        response = session.get(
            url,
            params=params,
            timeout=60
        )

        response.raise_for_status()
        data = response.json()

        for obj in data.get("items", []):
            yield obj

        token = data.get("nextPageToken")

        if not token:
            break


# ==========================================
# 2. VERIFIER LES FICHIERS
# ==========================================

def is_target(name):
    filename = Path(name).name

    prefix = (
        f"GAEZ-V5.RES05-SIX30AS."
        f"{SCENARIO}."
    )

    suffix = f".{WATER_INPUT}.tif"

    return (
        filename.startswith(prefix)
        and filename.endswith(suffix)
    )


def get_crop_code(name):
    filename = Path(name).name

    parts = filename.split(".")

    return parts[-3]


# ==========================================
# 3. SAUVEGARDER LE CATALOGUE
# ==========================================

def save_catalogue(objects):
    path = DEST / "gaez_catalogue.json"

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            objects,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(f"\nCatalogue enregistre : {path}")


# ==========================================
# 4. SELECTIONNER LES CULTURES
# ==========================================

def select_cultures(objects):
    selected = []

    for obj in objects:
        code = get_crop_code(obj["name"])

        if code in CULTURES:
            selected.append(obj)

    return selected


# ==========================================
# 5. AFFICHER LA SELECTION
# ==========================================

def show_selection(objects):
    print("\n========== CULTURES ==========\n")

    for index, obj in enumerate(objects, start=1):
        code = get_crop_code(obj["name"])
        culture = CULTURES[code]

        size_mb = int(
            obj.get("size", 0)
        ) / (1024 ** 2)

        print(
            f"{index:02d}. "
            f"{culture} ({code}) "
            f"- {size_mb:.2f} Mo"
        )

    total_bytes = sum(
        int(obj.get("size", 0))
        for obj in objects
    )

    print("\n==============================")

    print(f"Nombre de fichiers : {len(objects)}")

    print(
        f"Taille totale : "
        f"{total_bytes / (1024 ** 3):.2f} Go"
    )


# ==========================================
# 6. TELECHARGER UN FICHIER
# ==========================================

def download_file(obj):
    name = obj["name"]

    filename = Path(name).name
    destination = DEST / filename

    expected_size = int(obj.get("size", 0))

    if destination.exists():
        actual_size = destination.stat().st_size

        if expected_size > 0 and actual_size == expected_size:
            print("Deja telecharge.")
            return True

    url = (
        f"https://storage.googleapis.com/"
        f"{BUCKET}/{quote(name, safe='/')}"
    )

    temporary = DEST / (filename + ".part")

    try:
        with session.get(
            url,
            stream=True,
            timeout=(30, 120)
        ) as response:

            response.raise_for_status()

            with temporary.open("wb") as file:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        file.write(chunk)

        if expected_size > 0:
            actual_size = temporary.stat().st_size

            if actual_size != expected_size:
                print("Erreur : taille incorrecte.")
                return False

        temporary.replace(destination)

        print("Telechargement termine.")
        return True

    except requests.RequestException as error:
        print(f"Erreur reseau : {error}")
        return False

    except OSError as error:
        print(f"Erreur fichier : {error}")
        return False

    finally:
        temporary.unlink(missing_ok=True)


# ==========================================
# 7. TELECHARGEMENT AUTOMATIQUE
# ==========================================

def download_all(objects):
    success = 0
    failed = 0

    for index, obj in enumerate(objects, start=1):
        filename = Path(obj["name"]).name

        print(
            f"\n[{index}/{len(objects)}] "
            f"{filename}"
        )

        if download_file(obj):
            success += 1
        else:
            failed += 1

    print("\n========== RESULTAT ==========")
    print(f"Reussis : {success}")
    print(f"Echecs : {failed}")
    print(f"Dossier : {DEST}")


# ==========================================
# 8. PROGRAMME PRINCIPAL
# ==========================================

def main():
    catalogue_path = DEST / "gaez_catalogue.json"

    if catalogue_path.exists():
        print("Chargement du catalogue existant...")

        with catalogue_path.open(
            "r",
            encoding="utf-8"
        ) as file:
            objects = json.load(file)

    else:
        print("Recherche des fichiers GAEZ v5...")

        try:
            objects = [
                obj
                for obj in list_objects()
                if is_target(obj["name"])
            ]

        except requests.RequestException as error:
            print(f"Erreur API : {error}")
            return

        save_catalogue(objects)

    objects = [
        obj
        for obj in objects
        if is_target(obj["name"])
    ]

    print(f"\nFichiers GAEZ trouves : {len(objects)}")

    selected = select_cultures(objects)

    if not selected:
        print("Aucune culture trouvee.")
        return

    show_selection(selected)

    answer = input(
        "\nLancer le telechargement ? (oui/non) : "
    ).strip().lower()

    if answer != "oui":
        print("Telechargement annule.")
        return

    download_all(selected)


# ==========================================
# EXECUTION
# ==========================================

if __name__ == "__main__":
    main()
