#!/usr/bin/env python3
"""system/scripts/shop_export_amazon_session.py

⚠️  À EXÉCUTER SUR TON PC PERSONNEL — PAS SUR LE HOMEBOX.

Ce script ouvre un vrai navigateur Chromium visible sur TA machine, te laisse
te connecter à Amazon.fr toi-même (identifiant, mot de passe, 2FA — tout ça
se passe entre toi et Amazon, jamais via ce script ni via neronOS), puis
exporte uniquement les cookies de session résultants dans un fichier JSON.

Ce fichier NE CONTIENT PAS ton mot de passe. Il contient des cookies de
session déjà authentifiés — à traiter comme un mot de passe quand même
(quiconque le possède peut agir sur ton compte tant que la session est
valide) : ne le partage pas, ne le commit pas, transfère-le en privé.

Installation locale (une fois) :
    pip install playwright
    playwright install chromium

Utilisation :
    python3 shop_export_amazon_session.py

Puis transfert vers le homebox :
    scp shop_amazon_state.json neron@homebox:/etc/neronOS/data/shop_amazon_state.json
    ssh neron@homebox chmod 600 /etc/neronOS/data/shop_amazon_state.json

neronShop détecte automatiquement ce fichier au prochain lancement — aucun
redémarrage de service requis. Pour repasser en navigation anonyme, supprime
simplement /etc/neronOS/data/shop_amazon_state.json sur le homebox.
"""
from __future__ import annotations

import sys
from pathlib import Path

OUTPUT_PATH = Path(__file__).with_name("shop_amazon_state.json")


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright n'est pas installé sur cette machine.")
        print("Installe-le avec : pip install playwright && playwright install chromium")
        sys.exit(1)

    print("Ouverture d'un navigateur Chromium visible...")
    print("Connecte-toi normalement à Amazon.fr (identifiant, mot de passe, 2FA).")
    print("Reviens ensuite dans ce terminal et appuie sur Entrée.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(locale="fr-FR")
        page = context.new_page()
        page.goto("https://www.amazon.fr")

        input("Appuie sur Entrée une fois connecté à Amazon.fr dans la fenêtre ouverte... ")

        context.storage_state(path=str(OUTPUT_PATH))
        browser.close()

    print(f"\nSession exportée dans : {OUTPUT_PATH}")
    print("Prochaine étape — transfère ce fichier vers le homebox :")
    print(f"  scp {OUTPUT_PATH.name} neron@homebox:/etc/neronOS/data/shop_amazon_state.json")
    print("  ssh neron@homebox chmod 600 /etc/neronOS/data/shop_amazon_state.json")
    print("\nCe fichier donne accès à ta session Amazon — ne le laisse pas traîner,")
    print("supprime-le localement une fois transféré si tu n'en as plus besoin.")


if __name__ == "__main__":
    main()
