"""Rapport PDF (étape 12) : courbes, indices, pixels, cultures, rotations, limites."""
import io
import threading

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from modules_equipe.humidite import courbes as courbes_hum
from modules_equipe.temperature import courbes as courbes_temp

VERROU = threading.Lock()          # matplotlib : un dessin à la fois
STYLES = getSampleStyleSheet()
LIBELLES = {"retenue": "Retenue", "a_verifier": "À vérifier", "ecartee": "Écartée"}


def _p(texte, style="BodyText"):
    return Paragraph(str(texte), STYLES[style])


def _table(lignes, largeurs=None):
    t = Table([[_p(c) for c in l] for l in lignes], colWidths=largeurs, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6F2FD")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AFCDEE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _courbe(dessiner):
    tampon = io.BytesIO()
    with VERROU:
        dessiner(tampon)
    tampon.seek(0)
    return Image(tampon, width=17 * cm, height=7.2 * cm)


def generer(analyse, df, details):
    sortie = io.BytesIO()
    doc = SimpleDocTemplate(sortie, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="Rapport LEAF")
    e = []
    parc = analyse["parcelle"]
    e += [_p("Rapport LEAF — Aide au choix des cultures", "Title"),
          _p(f"Parcelle : {parc.get('nom') or '—'} · surface {parc['surface_ha']} ha · "
             f"plantation {parc['date_plantation']} · {'irriguée' if parc['irrigation'] else 'pluviale'}"),
          _p(f"Centre : {parc['centre_lat']:.5f}, {parc['centre_lon']:.5f} · période climatique "
             f"{analyse['climat']['periode']}"), Spacer(1, 8)]

    # Pixels
    e.append(_p("1. Pixels utilisés", "Heading2"))
    lignes = [["Source", "Taille d'un pixel", "Pixels touchés", "Parts de la parcelle"]]
    for res in analyse["pixels"].values():
        if not res:
            continue
        t = res["taille_pixel_km"]
        parts = ", ".join(f"{p['part']:.0%}" for p in res["pixels"][:8])
        lignes.append([res["source"], f"{t['largeur']} × {t['hauteur']} km (≈ {res['surface_pixel_ha']} ha)",
                       res["nb_pixels"], parts])
    e += [_table(lignes, [3.5 * cm, 5 * cm, 2.5 * cm, 6.4 * cm]),
          _p("Chaque valeur est celle du pixel entier : quand la parcelle touche plusieurs pixels, "
             "on fait la moyenne pondérée par la surface. Les données décrivent la zone, pas la parcelle seule."),
          Spacer(1, 8)]

    # Indices
    e.append(_p("2. Indices de stabilité (10 ans, 0 = instable, 1 = stable)", "Heading2"))
    ind = analyse["climat"]["indices"]
    e.append(_table([["Température", "Humidité (sol + air)", "Pluie", "Vent (provisoire)"],
                     [ind["temperature"], ind["humidite"], ind["pluie"], ind["vent"]]]))
    e.append(_p(f"Source pluie : {analyse['climat']['source_pluie']}"))
    try:
        e.append(_courbe(lambda t: courbes_temp.tracer_stabilite(
            df[["tmoy", "tmax", "tmin"]], details["temperature"], t, "", "NASA POWER")))
        e.append(_courbe(lambda t: courbes_hum.tracer_stabilite(
            df[["sol", "air"]], details["humidite"], t, "", "NASA POWER")))
    except Exception as erreur:          # le rapport reste utile sans les courbes
        e.append(_p(f"Courbes indisponibles : {erreur}"))

    # Saison
    e.append(_p("3. Conditions de la saison (normales mensuelles depuis la plantation)", "Heading2"))
    lignes = [["Mois", "T moy", "T max", "T min", "Pluie (mm)", "Humid. sol", "Humid. air %", "Vent m/s"]]
    for m in analyse["saison"]:
        lignes.append([m["nom"], m["tmoy"], m["tmax"], m["tmin"], m["pluie_mm"], m["humidite_sol"],
                       m["humidite_air"], m["vent_m_s"]])
    e += [_table(lignes), PageBreak()]

    # Cultures
    for statut, titre in [("retenue", "4. Cultures retenues"), ("a_verifier", "5. Cultures à vérifier"),
                          ("ecartee", "6. Cultures écartées")]:
        e.append(_p(titre, "Heading2"))
        liste = [c for c in analyse["cultures"] if c["statut"] == statut]
        if not liste:
            e.append(_p("Aucune."))
            continue
        lignes = [["Culture", "GAEZ (pixels)", "Justification"]]
        for c in liste:
            sol = c["sol"]
            gz = (f"classe {sol.get('classe_majoritaire')} {sol.get('aptitude', '')}"
                  + (" (hétérogène)" if sol.get("heterogene") else "")) if sol.get("statut") == "ok" else "—"
            just = (f"[{c['etape']}] " if c["etape"] else "") + " ; ".join(c["justification"])
            lignes.append([c["nom"], gz, just])
        e.append(_table(lignes, [3.5 * cm, 4 * cm, 9.9 * cm]))

    # Rotations
    e += [PageBreak(), _p("7. Comparaison des rotations proposées", "Heading2")]
    rot = analyse["rotations"]
    if rot["message"]:
        e.append(_p(rot["message"]))
    for r in rot["rotations"]:
        e.append(_p(f"Rotation {r['numero']} : {r['titre']}", "Heading3"))
        for titre, cle in [("Pourquoi", "pourquoi"), ("Preuves", "preuves"), ("Bénéfices", "benefices"),
                           ("Lacunes", "lacunes"), ("Risques", "risques")]:
            val = r[cle]
            e.append(_p(f"<b>{titre} :</b> " + (val if isinstance(val, str) else " ; ".join(val))))

    e += [Spacer(1, 10), _p("8. Limites et décision finale", "Heading2"),
          _p("Seuils des cultures, IS minimum et seuils GAEZ : valeurs PROVISOIRES à valider par l'agronome. "
             "Indice vent provisoire en attente du module de l'équipe. "
             "<b>La décision finale revient à l'agriculteur, avec un technicien agricole.</b>")]
    doc.build(e)
    return sortie.getvalue()
