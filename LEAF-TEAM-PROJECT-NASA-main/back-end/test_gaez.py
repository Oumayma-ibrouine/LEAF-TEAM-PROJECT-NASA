
import rasterio
from pathlib import Path
from rasterio.warp import transform

fichier = Path(__file__).parent / "data/gaez/GAEZ-V5.RES05-SIX30AS.HP0120.AGERA5.HIST.WHE.HILM.tif"

# Coordonnées GPS d'un champ à Béni Mellal
latitude = 32.423587
longitude = -6.380730
with rasterio.open(fichier) as src:
    print("Système de coordonnées :", src.crs)
    print("Résolution :", src.res)
    print("Nombre de bandes :", src.count)
    print("NoData :", src.nodata)

    # Conversion GPS vers le système du raster
    x, y = transform("EPSG:4326", src.crs, [longitude], [latitude])

    # Extraction de la valeur du pixel
    valeur = next(src.sample([(x[0], y[0])]))[0]

    print("Classe GAEZ :", valeur)
