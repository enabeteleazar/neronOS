"""core/agents/io/shop_agent.py
Neron Core — Agent neronShop  v0.1.0 (MVP)

Reçoit une demande d'achat en langage naturel ("achète-moi un câble USB-C
2m, budget max 15€"), cherche le produit sur Amazon.fr via Playwright,
sélectionne le meilleur candidat (ou remonte plusieurs options en cas
d'ambiguïté) et remplit le panier réel. NE VALIDE JAMAIS la commande
automatiquement : le remplissage du panier et la validation finale sont
deux points d'entrée séparés — process() et confirm_order().

Intent déclenché : SHOPPING_REQUEST
Commandes Telegram : /shop <demande>

Config dans neron.yaml (section `shop:`) :
  db_path            : chemin SQLite des demandes (défaut data/shop.db)
  headless           : navigateur headless ou non (défaut true)
  user_data_dir      : profil Chromium persistant (cookies/session Amazon)
  nav_timeout_ms     : timeout de navigation Playwright (défaut 15000)
  max_candidates     : nombre de résultats de recherche examinés (défaut 8)
  storage_state_path : session Amazon authentifiée optionnelle (défaut
                       data/shop_amazon_state.json), générée côté client par
                       system/scripts/shop_export_amazon_session.py. Aucun
                       mot de passe n'est jamais stocké ni manipulé par
                       l'agent — uniquement des cookies de session déjà
                       validés par Amazon (2FA compris) sur le poste de
                       l'utilisateur. Absence de fichier = navigation
                       anonyme (comportement par défaut, inchangé).

Limites connues (MVP) :
  - Volontairement AUCUNE technique de contournement de la détection
    anti-bot d'Amazon (pas de playwright-stealth, pas de délais "humains"
    simulés pour tromper la détection) — voir la note devant la section
    Playwright ci-dessous. En conséquence, Amazon.fr peut bloquer ou
    afficher un captcha plus souvent qu'avec ce type d'outillage ; l'agent
    échoue alors proprement (statut echec_bloque_anti_bot) plutôt que
    d'insister.
  - Sélecteurs CSS Amazon.fr fragiles : ils casseront si Amazon change son
    DOM (aucune garantie de stabilité, non couvert par des tests).
  - confirm_order() est un point d'entrée séparé mais ne déclenche pas le
    clic final « Passer la commande » dans ce MVP : automatiser une
    transaction financière réelle sans écran de revue humaine est un risque
    qu'on ne prend pas par défaut. Le point d'accroche est prêt.
  - Un seul marchand (Amazon.fr), pas de retry au-delà de l'échec propre.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from core.config import settings
from core.config.paths import NERON_DATA_DIR

logger = logging.getLogger("agent.shop")

# ── Dépendance optionnelle : Playwright ─────────────────────────────────────
#
# Automatisation "normale" uniquement : pas de playwright-stealth, pas de
# masquage de fingerprint (navigator.webdriver, user-agent, etc.), pas de
# délais aléatoires conçus pour imiter un comportement humain et tromper la
# détection anti-bot d'Amazon. Ce choix est volontaire (cf. docstring du
# module). Si Amazon bloque la requête, on le détecte et on échoue proprement
# — voir _detect_block() et ShopBlockedError.
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PlaywrightTimeoutError = Exception  # type: ignore[assignment,misc]
    _PLAYWRIGHT_AVAILABLE = False


# ── Config ────────────────────────────────────────────────────────────────────

_DB_PATH        = str(getattr(settings, "SHOP_DB_PATH", NERON_DATA_DIR / "shop.db"))
_HEADLESS       = bool(getattr(settings, "SHOP_HEADLESS", True))
_USER_DATA_DIR  = str(getattr(settings, "SHOP_USER_DATA_DIR", NERON_DATA_DIR / "shop_browser_profile"))
_NAV_TIMEOUT_MS = int(getattr(settings, "SHOP_NAV_TIMEOUT_MS", 15000))
_MAX_CANDIDATES = int(getattr(settings, "SHOP_MAX_CANDIDATES", 8))
_STORAGE_STATE_PATH = Path(getattr(settings, "SHOP_STORAGE_STATE_PATH", NERON_DATA_DIR / "shop_amazon_state.json"))

_AMAZON_BASE = "https://www.amazon.fr"

_CAPTCHA_MARKERS = [
    "saisissez les caractères",
    "type the characters you see",
    "entrez les caractères",
    "toutes nos excuses",
    "api-services-support@amazon.com",
    "/errors/validatecaptcha",
]


# ── Modèles Pydantic ──────────────────────────────────────────────────────────

class PurchaseCriteria(BaseModel):
    produit: str
    budget_max: Optional[float] = None
    quantite: int = 1
    marque: Optional[str] = None
    contraintes: list[str] = Field(default_factory=list)


class PurchaseCandidate(BaseModel):
    titre: str
    prix: Optional[float] = None
    url: str
    note: Optional[float] = None
    avis_count: Optional[int] = None


PurchaseStatus = Literal[
    "en_attente_validation",
    "ambigu_choix_requis",
    "echec_recherche",
    "echec_bloque_anti_bot",
    "echec_technique",
]


class PurchaseResult(BaseModel):
    id: str
    demande: str
    statut: PurchaseStatus
    produit: Optional[PurchaseCandidate] = None
    alternatives: list[PurchaseCandidate] = Field(default_factory=list)
    message: str = ""


class ShopBlockedError(Exception):
    """Levée quand Amazon.fr affiche un captcha ou bloque la requête."""


# ── SQLite (pattern lightweight du projet, cf. todo_agent.py) ──────────────────

@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _init_table() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_requests (
                id                TEXT PRIMARY KEY,
                demande_brute     TEXT NOT NULL,
                statut            TEXT NOT NULL,
                criteres_json     TEXT,
                produit_json      TEXT,
                alternatives_json TEXT,
                prix              REAL,
                url               TEXT,
                message           TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
        """)
        conn.commit()


def _insert_request(result: PurchaseResult, criteria: PurchaseCriteria) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO shop_requests (
                id, demande_brute, statut, criteres_json, produit_json,
                alternatives_json, prix, url, message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.id,
                result.demande,
                result.statut,
                criteria.model_dump_json(),
                result.produit.model_dump_json() if result.produit else None,
                json.dumps([a.model_dump() for a in result.alternatives], ensure_ascii=False),
                result.produit.prix if result.produit else None,
                result.produit.url if result.produit else None,
                result.message,
                now,
                now,
            ),
        )
        conn.commit()


def _get_request(request_id: str) -> Optional[sqlite3.Row]:
    with _db() as conn:
        return conn.execute(
            "SELECT * FROM shop_requests WHERE id = ?", (request_id,)
        ).fetchone()


# ── Parsing langage naturel ───────────────────────────────────────────────────

_TRIGGER_STRIP = re.compile(
    r"^(achete[- ]moi|achète[- ]moi|commande[- ]moi|trouve[- ]moi|cherche[- ]moi|prends[- ]moi)\s+",
    re.IGNORECASE,
)

_BUDGET_PATTERNS = [
    r"budget\s*max(?:imum)?\s*(?:de|:)?\s*(\d+(?:[.,]\d+)?)\s*(?:€|euros|eur)?",
    r"(?:max(?:imum)?|moins de|pas plus de|sous les?)\s*(\d+(?:[.,]\d+)?)\s*(?:€|euros|eur)",
    r"(\d+(?:[.,]\d+)?)\s*(?:€|euros|eur)\s*max(?:imum)?",
]

_QTY_WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5}

_QTY_PATTERNS = [
    r"\b(\d+)\s*(?:x|unités?|exemplaires?)\b",
    r"\bquantit[ée]\s*:?\s*(\d+)\b",
]

_BRAND_PATTERN = r"(?:de marque|marque)\s+([\w\-À-ÿ]+)"


def _extract_budget(query: str) -> Optional[float]:
    for pat in _BUDGET_PATTERNS:
        m = re.search(pat, query, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                continue
    return None


def _extract_quantity(query: str) -> int:
    q = query.lower()
    for pat in _QTY_PATTERNS:
        m = re.search(pat, q)
        if m:
            return max(1, int(m.group(1)))
    for word, val in _QTY_WORDS.items():
        if re.search(rf"\b{word}\b", q):
            return val
    return 1


def _extract_brand(query: str) -> Optional[str]:
    m = re.search(_BRAND_PATTERN, query, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extract_product(query: str) -> str:
    text = _TRIGGER_STRIP.sub("", query).strip()
    for pat in _BUDGET_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(_BRAND_PATTERN, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*,\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,.")
    return text or query.strip()


def _parse_criteria(query: str) -> PurchaseCriteria:
    return PurchaseCriteria(
        produit=_extract_product(query),
        budget_max=_extract_budget(query),
        quantite=_extract_quantity(query),
        marque=_extract_brand(query),
    )


# ── Extraction des résultats Amazon ────────────────────────────────────────────

def _parse_price(raw: str) -> Optional[float]:
    m = re.search(r"(\d+[.,]?\d*)", raw.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_rating(raw: str) -> Optional[float]:
    m = re.search(r"(\d+[.,]\d+)", raw)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


async def _detect_block(page) -> Optional[str]:
    """Détecte un captcha / blocage Amazon. Ne tente aucun contournement :
    on remonte l'échec tel quel (cf. note en tête de fichier)."""
    if "validatecaptcha" in page.url.lower() or "/errors/" in page.url.lower():
        return "Redirection vers une page de vérification Amazon (captcha probable)."
    try:
        content = (await page.content()).lower()
    except Exception:
        return None
    for marker in _CAPTCHA_MARKERS:
        if marker in content:
            return f"Contenu bloquant détecté (« {marker} »)."
    return None


async def _search_amazon(page, produit: str, max_results: int) -> list[PurchaseCandidate]:
    url = f"{_AMAZON_BASE}/s?k={quote_plus(produit)}"
    logger.info("Recherche Amazon.fr lancée : %s", url)
    await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)

    block = await _detect_block(page)
    if block:
        raise ShopBlockedError(block)

    try:
        await page.wait_for_selector('div[data-component-type="s-search-result"]', timeout=_NAV_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        raise ShopBlockedError(await _detect_block(page) or "Aucun résultat chargé (page inattendue).")

    cards = await page.query_selector_all('div[data-component-type="s-search-result"]')
    candidates: list[PurchaseCandidate] = []

    for card in cards[:max_results]:
        try:
            # Le lien produit est tantôt ancêtre, tantôt descendant du <h2>
            # selon les versions du front Amazon — on gère les deux via JS.
            h2_el = await card.query_selector("h2")
            title = (await h2_el.inner_text()).strip() if h2_el else None
            href  = await h2_el.evaluate(
                "el => el.querySelector('a')?.getAttribute('href') || el.closest('a')?.getAttribute('href') || null"
            ) if h2_el else None
            if not title or not href:
                continue

            price_el   = await card.query_selector("span.a-price > span.a-offscreen")
            rating_el  = await card.query_selector("span.a-icon-alt")
            reviews_el = await card.query_selector('a[aria-label*="évaluation"]')

            price = _parse_price(await price_el.inner_text()) if price_el else None
            note  = _parse_rating(await rating_el.inner_text()) if rating_el else None

            avis: Optional[int] = None
            if reviews_el:
                label = await reviews_el.get_attribute("aria-label")
                digits = re.sub(r"[^\d]", "", label) if label else ""
                if digits:
                    avis = int(digits)

            candidates.append(PurchaseCandidate(
                titre=title,
                prix=price,
                url=href if href.startswith("http") else f"{_AMAZON_BASE}{href}",
                note=note,
                avis_count=avis,
            ))
        except Exception as e:
            logger.debug("Carte produit ignorée (extraction impossible) : %s", e)
            continue

    logger.info("%d candidat(s) extrait(s) pour « %s »", len(candidates), produit)
    return candidates


def _select_candidate(
    candidates: list[PurchaseCandidate],
    criteria: PurchaseCriteria,
) -> tuple[Optional[PurchaseCandidate], list[PurchaseCandidate], bool]:
    pool = candidates

    if criteria.budget_max is not None:
        within_budget = [c for c in pool if c.prix is not None and c.prix <= criteria.budget_max]
        if within_budget:
            pool = within_budget

    if criteria.marque:
        marque_lower = criteria.marque.lower()
        matching_brand = [c for c in pool if marque_lower in c.titre.lower()]
        if matching_brand:
            pool = matching_brand

    priced = [c for c in pool if c.prix is not None]
    pool = priced or pool
    if not pool:
        return None, [], False

    ranked = sorted(pool, key=lambda c: (-(c.note or 0.0), c.prix if c.prix is not None else float("inf")))
    best = ranked[0]
    alternatives = ranked[1:4]

    ambiguous = False
    if alternatives:
        runner_up = alternatives[0]
        close_price = (
            best.prix is not None and runner_up.prix is not None
            and best.prix > 0
            and abs(best.prix - runner_up.prix) / best.prix < 0.15
        )
        close_rating = (runner_up.note or 0.0) >= (best.note or 0.0) - 0.3
        if close_price and close_rating:
            ambiguous = True

    return best, alternatives, ambiguous


async def _add_to_cart(page, candidate: PurchaseCandidate, quantite: int) -> None:
    logger.info("Ouverture de la fiche produit : %s", candidate.url)
    await page.goto(candidate.url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)

    block = await _detect_block(page)
    if block:
        raise ShopBlockedError(block)

    if quantite > 1:
        try:
            await page.select_option("#quantity", str(quantite))
        except Exception:
            logger.warning("Sélecteur de quantité introuvable — quantité par défaut (1) conservée.")

    try:
        await page.click("#add-to-cart-button", timeout=_NAV_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        raise ShopBlockedError(await _detect_block(page) or "Bouton « Ajouter au panier » introuvable.")

    try:
        await page.wait_for_selector(
            "#huc-v2-order-row-confirm-text, #NATC_SMART_WAGON_CONF_MSG_SUCCESS, #attach-accept-button, #sw-atc-details",
            timeout=_NAV_TIMEOUT_MS,
        )
        logger.info("Confirmation d'ajout au panier détectée pour « %s ».", candidate.titre)
    except PlaywrightTimeoutError:
        logger.warning("Confirmation d'ajout au panier non détectée — le panier a peut-être été rempli malgré tout.")


async def _seed_authenticated_session(context) -> None:
    """Injecte les cookies d'une session Amazon déjà authentifiée, si un export
    storage_state existe (généré côté client par
    system/scripts/shop_export_amazon_session.py — jamais de mot de passe ici,
    uniquement des cookies de session déjà validés par Amazon). Absence de
    fichier = navigation anonyme, comportement inchangé."""
    if not _STORAGE_STATE_PATH.exists():
        return
    try:
        data = json.loads(_STORAGE_STATE_PATH.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        if cookies:
            await context.add_cookies(cookies)
            logger.info(
                "Session Amazon authentifiée chargée depuis %s (%d cookies).",
                _STORAGE_STATE_PATH, len(cookies),
            )
    except Exception as e:
        logger.warning("Session Amazon illisible (%s) — repli sur navigation anonyme.", e)


@asynccontextmanager
async def _browser_page():
    """Contexte Chromium persistant (cookies/session Amazon conservés entre
    exécutions) — headless configurable, sans aucun masquage de fingerprint."""
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=_USER_DATA_DIR,
            headless=_HEADLESS,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1366, "height": 900},
        )
        try:
            await _seed_authenticated_session(context)
            page = context.pages[0] if context.pages else await context.new_page()
            yield page
        finally:
            await context.close()


# ── Formatage texte (convention du dossier : run() retourne du texte) ─────────

def _format_result(result: PurchaseResult) -> str:
    if result.statut == "en_attente_validation" and result.produit:
        prix = f"{result.produit.prix} €" if result.produit.prix is not None else "prix inconnu"
        return (
            f"🛒 **{result.produit.titre}**\n"
            f"💶 {prix}\n"
            f"🔗 {result.produit.url}\n\n"
            f"✅ {result.message}\n"
            f"🆔 Référence demande : {result.id}"
        )

    if result.statut == "ambigu_choix_requis" and result.produit:
        lines = [f"🤔 {result.message}", ""]
        options = [result.produit, *result.alternatives]
        for i, opt in enumerate(options, start=1):
            prix = f"{opt.prix} €" if opt.prix is not None else "prix inconnu"
            lines.append(f"{i}. {opt.titre} — {prix}")
        lines.append(f"\n🆔 Référence demande : {result.id}")
        return "\n".join(lines)

    if result.statut == "echec_bloque_anti_bot":
        return f"🚫 {result.message}\nRéessaie plus tard ou effectue l'achat manuellement sur Amazon.fr."

    return f"⚠️ {result.message}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class ShopAgent:
    """
    Recherche un produit sur Amazon.fr à partir d'une demande en langage
    naturel, sélectionne le meilleur candidat (ou remonte plusieurs options
    en cas d'ambiguïté) et remplit le panier réel via Playwright.
    Ne valide JAMAIS la commande — voir confirm_order() pour la validation
    finale, qui est un point d'entrée explicite et séparé.
    """

    def __init__(self) -> None:
        _init_table()

    async def process(self, query: str) -> PurchaseResult:
        """Flux structuré (Pydantic) : parsing → recherche → sélection →
        remplissage panier. S'arrête toujours avant tout écran de paiement."""
        request_id = str(uuid.uuid4())
        criteria = _parse_criteria(query)
        logger.info("Nouvelle demande d'achat #%s : %r → critères %r", request_id, query, criteria)

        if not criteria.produit:
            result = PurchaseResult(
                id=request_id, demande=query, statut="echec_recherche",
                message="Produit non identifié dans la demande — précise l'article recherché.",
            )
            _insert_request(result, criteria)
            return result

        if not _PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright n'est pas installé — impossible d'exécuter neronShop.")
            result = PurchaseResult(
                id=request_id, demande=query, statut="echec_technique",
                message="Playwright n'est pas installé sur ce serveur "
                        "(pip install playwright && playwright install chromium).",
            )
            _insert_request(result, criteria)
            return result

        try:
            async with _browser_page() as page:
                candidates = await _search_amazon(page, criteria.produit, _MAX_CANDIDATES)
                if not candidates:
                    result = PurchaseResult(
                        id=request_id, demande=query, statut="echec_recherche",
                        message=f"Aucun résultat Amazon.fr pour « {criteria.produit} ».",
                    )
                    _insert_request(result, criteria)
                    return result

                best, alternatives, ambiguous = _select_candidate(candidates, criteria)
                if best is None:
                    result = PurchaseResult(
                        id=request_id, demande=query, statut="echec_recherche",
                        message="Aucun candidat ne correspond aux critères (budget/marque).",
                    )
                    _insert_request(result, criteria)
                    return result

                if ambiguous:
                    logger.info("Choix ambigu pour #%s — %d alternative(s) proposée(s).", request_id, len(alternatives))
                    result = PurchaseResult(
                        id=request_id, demande=query, statut="ambigu_choix_requis",
                        produit=best, alternatives=alternatives,
                        message="Plusieurs produits se valent — précise lequel choisir avant de remplir le panier.",
                    )
                    _insert_request(result, criteria)
                    return result

                await _add_to_cart(page, best, criteria.quantite)

                logger.info("Panier rempli pour #%s : %s (%s €)", request_id, best.titre, best.prix)
                result = PurchaseResult(
                    id=request_id, demande=query, statut="en_attente_validation",
                    produit=best, alternatives=alternatives,
                    message=(
                        f"« {best.titre} » ajouté au panier Amazon.fr. "
                        "En attente de validation manuelle — aucune commande n'a été passée."
                    ),
                )
                _insert_request(result, criteria)
                return result

        except ShopBlockedError as e:
            logger.warning("Blocage anti-bot détecté pour #%s : %s", request_id, e)
            result = PurchaseResult(
                id=request_id, demande=query, statut="echec_bloque_anti_bot",
                message=f"Amazon.fr a bloqué la requête : {e}",
            )
            _insert_request(result, criteria)
            return result

        except Exception as e:
            logger.error("ShopAgent error pour la demande #%s : %s", request_id, e)
            result = PurchaseResult(
                id=request_id, demande=query, statut="echec_technique",
                message="Erreur technique inattendue pendant la recherche ou le remplissage du panier.",
            )
            _insert_request(result, criteria)
            return result

    async def confirm_order(self, request_id: str) -> PurchaseResult:
        """
        Point d'entrée EXPLICITE et séparé pour la validation finale.
        À n'appeler qu'après revue humaine du panier. N'est jamais invoqué
        automatiquement par process().

        MVP : ne déclenche pas le clic « Passer la commande » — automatiser
        une transaction financière réelle sans écran de revue humaine est un
        risque qu'on ne prend pas par défaut. Ce point d'entrée est prêt à
        être complété si ce comportement est explicitement voulu.
        """
        row = _get_request(request_id)
        if row is None:
            return PurchaseResult(
                id=request_id, demande="", statut="echec_technique",
                message="Demande introuvable.",
            )

        if row["statut"] != "en_attente_validation":
            return PurchaseResult(
                id=request_id, demande=row["demande_brute"], statut=row["statut"],
                message=f"Cette demande n'est pas en attente de validation (statut actuel : {row['statut']}).",
            )

        logger.info("Validation manuelle demandée pour #%s — non automatisée dans ce MVP.", request_id)
        return PurchaseResult(
            id=request_id, demande=row["demande_brute"], statut="en_attente_validation",
            message="Validation non automatisée dans ce MVP : ouvre le panier Amazon.fr et valide toi-même la commande.",
        )

    async def run(self, query: str = "") -> str:
        """Point d'entrée conventionnel du dossier io/ — retourne du texte formaté."""
        result = await self.process(query)
        return _format_result(result)
