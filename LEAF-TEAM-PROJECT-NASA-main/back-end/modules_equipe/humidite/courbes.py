"""Courbes matplotlib : série temporelle sur 10 ans et indice de stabilité par mois (sol + air)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .analyse import is_par_mois, periode_dix_ans

BRUN, BRUN_FONCE, BLEU, BLEU_FONCE, GRIS = "#BA7517", "#854F0B", "#378ADD", "#185FA5", "#444441"


def _enregistrer(fig, chemin):
    """chemin = nom de fichier (str) ou objet fichier en mémoire (io.BytesIO, pour l'API)."""
    fig.tight_layout()
    if isinstance(chemin, str):
        os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    fig.savefig(chemin, dpi=150, format="png")
    plt.close(fig)
    return chemin


def tracer_serie_temporelle(df, chemin, titre_lieu="", source="NASA POWER"):
    """Série temporelle des 10 ans : valeurs journalières + moyennes mensuelles (sol en haut, air en bas)."""
    debut, fin = periode_dix_ans(df)
    p = df.loc[f"{debut}-01-01":f"{fin}-12-31"]
    mensuel = p.resample("MS").mean()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    ax1.plot(p.index, p["sol"], color=BRUN, lw=0.5, alpha=0.6, label="Sol (zone racinaire) : journalier")
    ax1.plot(mensuel.index, mensuel["sol"], color=BRUN_FONCE, lw=2.2, marker="o", ms=3, label="Sol : moyenne mensuelle")
    ax1.set_ylim(0, 1)
    ax1.set_ylabel("Humidité du sol (0 = sec, 1 = saturé)")
    ax1.set_title(f"Série temporelle de l'humidité ({debut} → {fin})"
                  f"{' — ' + titre_lieu if titre_lieu else ''}\nSource : {source}", fontsize=12)
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8, loc="upper right")

    ax2.plot(p.index, p["air"], color=BLEU, lw=0.5, alpha=0.6, label="Air : journalier")
    ax2.plot(mensuel.index, mensuel["air"], color=BLEU_FONCE, lw=2.2, marker="o", ms=3, label="Air : moyenne mensuelle")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("Humidité de l'air (%)")
    ax2.set_xlabel("Date")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8, loc="lower right")
    return _enregistrer(fig, chemin)


def tracer_stabilite(df, resultat, chemin, titre_lieu="", source="NASA POWER"):
    """IS de chaque mois pour le sol et l'air (barres) + IS humidité final (ligne)."""
    mois, debut, fin = is_par_mois(df)
    sol = np.array([np.nan if m["is_sol"] is None else m["is_sol"] for m in mois], dtype=float)
    air = np.array([np.nan if m["is_air"] is None else m["is_air"] for m in mois], dtype=float)
    x = np.arange(12)
    largeur = 0.4
    is_final = resultat["is_humidite"]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x - largeur / 2, np.nan_to_num(sol), largeur, color=BRUN, alpha=0.8, label="IS sol du mois")
    ax.bar(x + largeur / 2, np.nan_to_num(air), largeur, color=BLEU, alpha=0.8, hatch="//",
           edgecolor="white", label="IS air du mois")
    if is_final is not None:
        ax.axhline(is_final, color=GRIS, lw=2, ls="--", label=f"IS humidité = {is_final:.2f}")
    ax.set_xticks(x, [m["mois"] for m in mois])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Indice de stabilité (0 à 1)")
    ax.set_title(f"Indice de stabilité de l'humidité ({debut} → {fin})"
                 f"{' — ' + titre_lieu if titre_lieu else ''}\nIS humidité = moyenne(IS sol, IS air) · Source : {source}",
                 fontsize=11)
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)
    return _enregistrer(fig, chemin)
