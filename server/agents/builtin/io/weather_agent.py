"""core/agents/io/weather_agent.py
Neron Core — Agent Météo  v1.2.0

Inspiré de helpers.py (JARVIS) — météo temps réel via Open-Meteo (100 % gratuit,
sans clé API) + géocodage via Nominatim (OpenStreetMap).

Quand la query ne nomme aucune ville, l'agent se géolocalise lui-même via son
IP publique (ipapi.co, gratuit, sans clé) plutôt que de retomber directement
sur une ville par défaut fixe. Le résultat de géolocalisation est mis en
cache le temps du process : l'IP du serveur ne change pas d'une requête à
l'autre, inutile de re-frapper le service à chaque « météo ? ».

Intent déclenché : WEATHER_QUERY
Commandes Telegram : /meteo [ville]

Config dans neron.yaml (section `weather:`) :
  default_city: "Paris"   # repli si la ville n'est pas précisée ET que la
                           # géolocalisation IP échoue
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger("agent.weather")

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_CITY = getattr(settings, "WEATHER_DEFAULT_CITY", "Paris")

_GEOCODE_URL   = "https://nominatim.openstreetmap.org/search"
_WEATHER_URL   = "https://api.open-meteo.com/v1/forecast"
_LOCATE_URL    = "https://ipapi.co/json/"
_LOCATE_CACHE_TTL = 3600.0  # secondes — l'IP du serveur ne bouge pas souvent

# Codes WMO → description + emoji
_WMO_CODES: dict[int, tuple[str, str]] = {
    0:  ("Ciel dégagé",         "☀️"),
    1:  ("Principalement clair","🌤️"),
    2:  ("Partiellement nuageux","⛅"),
    3:  ("Couvert",             "☁️"),
    45: ("Brouillard",          "🌫️"),
    48: ("Brouillard givrant",  "🌫️"),
    51: ("Bruine légère",       "🌦️"),
    53: ("Bruine modérée",      "🌦️"),
    55: ("Bruine dense",        "🌧️"),
    61: ("Pluie légère",        "🌧️"),
    63: ("Pluie modérée",       "🌧️"),
    65: ("Pluie forte",         "🌧️"),
    71: ("Neige légère",        "🌨️"),
    73: ("Neige modérée",       "❄️"),
    75: ("Neige forte",         "❄️"),
    80: ("Averses légères",     "🌦️"),
    81: ("Averses modérées",    "🌧️"),
    82: ("Averses violentes",   "⛈️"),
    95: ("Orage",               "⛈️"),
    99: ("Orage avec grêle",    "⛈️"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_city(query: str) -> Optional[str]:
    """Tente d'extraire une ville explicitement nommée dans la query.

    Exemples couverts :
      'météo à Lyon'                     → Lyon
      'quel temps fait-il à Marseille'   → Marseille
      'il fait combien à Nice'           → Nice
      'météo Paris'                      → Paris
      'il fait combien'                  → None (pas de ville → auto-localisation)
    """
    patterns = [
        # "météo à Lyon", "météo de Paris"
        r"(?:météo|meteo|température|temperature)\s+(?:à|a|de|sur|pour)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]*?)(?:\s*\?|$)",
        # "quel temps fait-il à Marseille", "il fait combien à Nice"
        # \b avant (à|a) : sans lui, le "a" final de "la" (ex. "la météo ?")
        # matchait et renvoyait "météo" comme fausse ville.
        r"\b(?:à|a)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]{2,})(?:\s*[?]|$)",
        # "météo Lyon" (sans préposition)
        r"(?:météo|meteo)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]{2,})(?:\s*[?]|$)",
    ]
    for pat in patterns:
        m = re.search(pat, query, re.IGNORECASE)
        if m:
            city = m.group(1).strip().rstrip("?").strip()
            if 2 < len(city) < 50:
                return city
    return None


async def _geocode(city: str) -> tuple[float, float]:
    """Retourne (lat, lon) pour une ville via Nominatim."""
    async with httpx.AsyncClient(
        timeout=6.0,
        headers={"User-Agent": "Neron-Assistant/1.0 (homebox self-hosted)"},
    ) as client:
        r = await client.get(_GEOCODE_URL, params={
            "q": city, "format": "json", "limit": 1,
        })
        r.raise_for_status()
        data = r.json()
        if not data:
            raise ValueError(f"Ville introuvable : {city}")
        return float(data[0]["lat"]), float(data[0]["lon"])


# Cache process-local du dernier résultat de géolocalisation IP.
_locate_cache: Optional[tuple[float, float, str]] = None
_locate_cache_ts: float = 0.0


async def _locate_self() -> tuple[float, float, str]:
    """Géolocalise le serveur via son IP publique (ipapi.co, gratuit, sans clé).

    Retourne (lat, lon, ville). Résultat mis en cache _LOCATE_CACHE_TTL
    secondes pour éviter une requête externe à chaque question sans ville.
    """
    global _locate_cache, _locate_cache_ts

    now = time.monotonic()
    if _locate_cache is not None and (now - _locate_cache_ts) < _LOCATE_CACHE_TTL:
        return _locate_cache

    async with httpx.AsyncClient(
        timeout=5.0,
        headers={"User-Agent": "Neron-Assistant/1.0 (homebox self-hosted)"},
    ) as client:
        r = await client.get(_LOCATE_URL)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise ValueError(data.get("reason", "Géolocalisation IP indisponible"))

        lat = float(data["latitude"])
        lon = float(data["longitude"])
        city = data.get("city") or _DEFAULT_CITY

    _locate_cache = (lat, lon, city)
    _locate_cache_ts = now
    return _locate_cache


async def _fetch_weather(lat: float, lon: float) -> dict:
    """Récupère les données météo Open-Meteo."""
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(_WEATHER_URL, params={
            "latitude":  lat,
            "longitude": lon,
            "current":   "temperature_2m,relative_humidity_2m,apparent_temperature,"
                         "weather_code,wind_speed_10m,precipitation",
            "timezone":  "Europe/Paris",
        })
        r.raise_for_status()
        return r.json()


def _format_weather(data: dict, city: str) -> str:
    """Formate la réponse météo en texte lisible."""
    cur  = data.get("current", {})
    code = int(cur.get("weather_code", 0))
    desc, emoji = _WMO_CODES.get(code, ("Inconnu", "🌡️"))

    temp     = cur.get("temperature_2m", "?")
    feels    = cur.get("apparent_temperature", "?")
    humidity = cur.get("relative_humidity_2m", "?")
    wind     = cur.get("wind_speed_10m", "?")
    precip   = cur.get("precipitation", 0)

    lines = [
        f"{emoji} **Météo à {city}** — {desc}",
        f"🌡️ Température : {temp}°C (ressenti {feels}°C)",
        f"💧 Humidité : {humidity}%",
        f"💨 Vent : {wind} km/h",
    ]
    if precip and float(precip) > 0:
        lines.append(f"🌧️ Précipitations : {precip} mm")
    return "\n".join(lines)


# ── Agent ─────────────────────────────────────────────────────────────────────

class WeatherAgent:
    """
    Retourne la météo actuelle pour une ville, ou pour la position du
    serveur (auto-localisation IP) si aucune ville n'est précisée.
    Utilise Open-Meteo (gratuit, sans clé) + Nominatim pour le géocodage.
    """

    async def run(self, query: str = "") -> str:
        city = _extract_city(query)
        try:
            if city:
                lat, lon = await _geocode(city)
            else:
                try:
                    lat, lon, city = await _locate_self()
                except Exception as e:
                    logger.warning("Auto-localisation impossible, repli sur %s : %s", _DEFAULT_CITY, e)
                    city = _DEFAULT_CITY
                    lat, lon = await _geocode(city)

            data = await _fetch_weather(lat, lon)
            return _format_weather(data, city)

        except ValueError as e:
            return f"⚠️ {e}"
        except httpx.TimeoutException:
            return "⚠️ Délai dépassé lors de la récupération de la météo."
        except Exception as e:
            logger.error("WeatherAgent error for '%s': %s", city, e)
            return f"Impossible de récupérer la météo pour « {city} »."
