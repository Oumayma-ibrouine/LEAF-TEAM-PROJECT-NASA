"""Courbes matplotlib : série temporelle sur 10 ans et indice de stabilité par mois."""
import os

import matplotlib
matplotlib.use("Agg")                    # pas besoin d'écran : on enregistre en PNG
import matplotlib.pyplot as plt
import numpy as np

from .analyse import is_par_mois, periode_dix_ans

ROUGE, ROUGE_FONCE, BLEU, BLEU_FONCE, GRIS = "#D85A30", "#A32D2D", "#378ADD", "#185FA5", "#5F5E5A"


def _enregistrer(fig, chemin):
    """chemin = nom de fichier (str) ou objet fichier en mémoire (io.BytesIO, pour l'API)."""
    fig.tight_layout()
    if isinstance(chemin, str):
        os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    fig.savefig(chemin, dpi=150, format="png")
    plt.close(fig)
    return chemin


def tracer_serie_temporelle(df, chemin, titre_lieu="", source="NASA POWER"):
    """Série temporelle des 10 ans : valeurs journalières + moyennes mensuelles."""
    debut, fin = periode_dix_ans(df)
    p = df.loc[f"{debut}-01-01":f"{fin}-12-31"]
    mensuel = p.resample("MS").mean()

    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.fill_between(p.index, p["tmin"], p["tmax"], color=ROUGE, alpha=0.12, label="Journalier : Tmin → Tmax")
    ax.plot(p.index, p["tmoy"], color=GRIS, lw=0.4, alpha=0.6, label="Température moyenne journalière")
    ax.plot(mensuel.index, mensuel["tmoy"], color=ROUGE_FONCE, lw=2.2, marker="o", ms=3,
            label="Température moyenne mensuelle")
    ax.set_ylabel("Température (°C)")
    ax.set_xlabel("Date")
    ax.set_title(f"Série temporelle de la température ({debut} → {fin})"
                 f"{' — ' + titre_lieu if titre_lieu else ''}\nSource : {source}", fontsize=12)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3)
    return _enregistrer(fig, chemin)


def tracer_stabilite(df, resultat, chemin, titre_lieu="", source="NASA POWER"):
    """IS de chaque mois (barres) + IS final (ligne)."""
    mois, debut, fin = is_par_mois(df)
    valeurs = np.array([np.nan if m["is"] is None else m["is"] for m in mois], dtype=float)
    x = np.arange(12)
    is_final = resultat["is_temperature"]

    fig, ax = plt.subplots(figsize=(12, 5))
    barres = ax.bar(x, np.nan_to_num(valeurs), color=BLEU, alpha=0.75, label="IS du mois")
    for barre, v in zip(barres, valeurs):
        if not np.isnan(v):
            ax.text(barre.get_x() + barre.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=8)
    if is_final is not None:
        ax.axhline(is_final, color=BLEU_FONCE, lw=2, ls="--", label=f"IS température = {is_final:.2f}")
    ax.set_xticks(x, [m["mois"] for m in mois])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Indice de stabilité (0 à 1)")
    ax.set_title(f"Indice de stabilité de la température ({debut} → {fin})"
                 f"{' — ' + titre_lieu if titre_lieu else ''}\n{resultat['parametres']['formule']} · Source : {source}",
                 fontsize=11)
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)
    return _enregistrer(fig, chemin)
