#!/usr/bin/env python3
"""V5 — validation production controlee, mesure avant/apres.

Contrairement a V1-V4, ce script tape DIRECTEMENT sur le service de
production reel (127.0.1.2:8765, neron@llm.service) — aucune instance
jetable. Le changement de configuration (neron.yaml) et le redemarrage du
service sont geres HORS de ce script, comme des actions visibles et
individuelles dans la conversation (pas d'automatisation opaque pour une
mutation de production).

Ce script se contente de :
  - envoyer les prompts (sequentiellement, jamais en parallele) ;
  - classer chaque reponse (COMPLETE/TRUNCATED/INCORRECT/EMPTY/ERROR) ;
  - agreger les stats ;
  - ecrire raw/summary/meta timestamps, un jeu de fichiers par phase.

Usage :
    python tools/benchmark_llm_v5.py --phase before
    python tools/benchmark_llm_v5.py --phase after --warmup 2
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_llm import RESULTS_DIR, get_hardware_info  # noqa: E402

NERON_LLM_URL = "http://127.0.1.2:8765/llm/generate"
API_KEY = os.getenv("NERON_API_KEY", "")
TOKENS_PER_WORD_RATIO = 1.85  # mesure empirique V2, reutilisee pour limit_hit_rate estime

# ── Datasets (mission V5, sections 5 et 11) ───────────────────────────────

BEFORE_PROMPTS: list[dict] = [
    {"id": "A1", "cat": "A_courte", "prompt": "Quelle est la capitale de la France ?", "expected": "paris"},
    {"id": "A2", "cat": "A_courte", "prompt": "Combien font 27 + 35 ?", "expected": "62"},
    {"id": "A3", "cat": "A_courte", "prompt": "Combien font 12 x 8 ?", "expected": "96"},
    {"id": "A4", "cat": "A_courte", "prompt": "Quel jour vient apres lundi ?", "expected": "mardi"},
    {"id": "A5", "cat": "A_courte", "prompt": "Combien de minutes y a-t-il dans une heure ?", "expected": "60"},
    {"id": "C1", "cat": "C_stricte", "prompt": "Reponds uniquement par OK.", "expected": "ok"},
    {"id": "C2", "cat": "C_stricte", "prompt": "Reponds uniquement par OUI ou NON.", "expected": None},
    {"id": "C3", "cat": "C_stricte", "prompt": "Donne uniquement le resultat de 27 + 35.", "expected": "62"},
    {"id": "C4", "cat": "C_stricte", "prompt": "Reponds en une seule phrase.", "expected": None},
    {"id": "C5", "cat": "C_stricte", "prompt": "Ne donne aucune explication.", "expected": None},
    {"id": "D1", "cat": "D_raisonnement", "prompt": "Si j'ai 3 pommes et que j'en achete 5, combien ai-je de pommes ?", "expected": "8"},
    {"id": "D2", "cat": "D_raisonnement", "prompt": "Il est 8h30 et un trajet dure 1h45. A quelle heure arrive-t-on ?", "expected": "10h15"},
    {"id": "D3", "cat": "D_raisonnement", "prompt": "Pierre a 10 euros. Il depense 3 euros. Combien lui reste-t-il ?", "expected": "7"},
    {"id": "E1", "cat": "E_contexte", "prompt": "Qui es-tu ?", "expected": None},
    {"id": "E2", "cat": "E_contexte", "prompt": "Que peux-tu faire ?", "expected": None},
    {"id": "E3", "cat": "E_contexte", "prompt": "Comment fonctionnes-tu ?", "expected": None},
    {"id": "E4", "cat": "E_contexte", "prompt": "Quel est ton role ?", "expected": None},
    {"id": "E5", "cat": "E_contexte", "prompt": "Que sais-tu faire actuellement ?", "expected": None},
]

AFTER_PROMPTS: list[dict] = BEFORE_PROMPTS + [
    {"id": "B1", "cat": "B_naturelle", "prompt": "Explique-moi simplement ce qu'est Linux.", "expected": None},
    {"id": "B2", "cat": "B_naturelle", "prompt": "A quoi sert une API REST ?", "expected": None},
    {"id": "B3", "cat": "B_naturelle", "prompt": "Quelle est la difference entre une IA et un LLM ?", "expected": None},
    {"id": "B4", "cat": "B_naturelle", "prompt": "Qu'est-ce qu'un mot de passe fort ?", "expected": None},
    {"id": "B5", "cat": "B_naturelle", "prompt": "Pourquoi redemarrer un ordinateur peut resoudre un probleme ?", "expected": None},
    {"id": "D4", "cat": "D_raisonnement", "prompt": "Pierre a 10 pommes. Il en donne 3 a Paul puis achete 5 pommes. Combien lui reste-t-il de pommes ?", "expected": "12"},
    {"id": "D5", "cat": "D_raisonnement", "prompt": "Un film commence a 20h30 et dure 2h15. A quelle heure se termine-t-il ?", "expected": "22h45"},
    {"id": "L1", "cat": "L_longueur", "prompt": "Explique-moi les principales differences entre Linux et Windows en quelques points.", "expected": None},
    {"id": "L2", "cat": "L_longueur", "prompt": "Explique-moi simplement comment fonctionne un serveur web.", "expected": None},
    {"id": "L3", "cat": "L_longueur", "prompt": "Explique le fonctionnement general d'un LLM a quelqu'un qui ne connait pas l'intelligence artificielle.", "expected": None},
]


# ── Appel production reel ──────────────────────────────────────────────

def call_generate(prompt: str, timeout_s: float) -> dict:
    t0 = time.monotonic()
    error = None
    result_text = None
    latency_ms_api = None
    model_used = None
    status_code = None
    if not API_KEY:
        return {"error": "NERON_API_KEY absente", "http_status": None, "response_text": None,
                "latency_ms_client": 0, "model_used": None}
    try:
        r = httpx.post(
            NERON_LLM_URL,
            json={"task_type": "chat", "prompt": prompt},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=timeout_s,
        )
        status_code = r.status_code
        wall_s = time.monotonic() - t0
        if r.status_code == 200:
            data = r.json()
            result_text = data.get("result")
            latency_ms_api = data.get("latency_ms")
            model_used = data.get("model_used")
        else:
            error = f"HTTP {r.status_code}: {r.text[:200]}"
    except httpx.TimeoutException:
        wall_s = time.monotonic() - t0
        error = f"timeout > {timeout_s}s"
    except Exception as exc:
        wall_s = time.monotonic() - t0
        error = str(exc)

    return {
        "http_status": status_code, "error": error, "response_text": result_text,
        "model_used": model_used,
        "response_len_chars": len(result_text) if result_text else 0,
        "response_len_words": len(result_text.split()) if result_text else 0,
        "latency_ms_client": round(wall_s * 1000),
        "latency_ms_api_reported": latency_ms_api,
        "eval_count": "unavailable", "ttft_ms": "unavailable", "tokens_per_second": "unavailable",
    }


def classify_response(text: str | None, error: str | None, num_predict_hint: int, expected: str | None) -> list[str]:
    tags: list[str] = []
    if error:
        tags.append("ERROR")
        return tags
    if not text or not text.strip():
        tags.append("EMPTY")
        return tags
    stripped = text.rstrip()
    words = stripped.split()
    est_tokens = len(words) * TOKENS_PER_WORD_RATIO
    ends_clean = bool(re.search(r'[.!?»":]$', stripped)) or stripped.endswith(("OK", "ok"))
    last_word = words[-1] if words else ""
    looks_cut_word = (not ends_clean) and len(last_word) > 2 and last_word.isalpha()
    near_limit = est_tokens >= max(5, num_predict_hint - 8) if num_predict_hint > 0 else False
    truncated = (not ends_clean) and (near_limit or looks_cut_word) and len(words) >= 3
    tags.append("TRUNCATED" if truncated else "COMPLETE")

    if expected is not None:
        norm = re.sub(r"[^a-z0-9]", "", text.lower())
        norm_expected = re.sub(r"[^a-z0-9]", "", expected.lower())
        tags.append("CORRECT" if norm_expected in norm else "INCORRECT")
    return tags


def system_snapshot() -> dict:
    load1, load5, load15 = os.getloadavg()
    hw = get_hardware_info()
    with open("/proc/meminfo") as f:
        meminfo = f.read()
    swap_total = int(re.search(r"SwapTotal:\s+(\d+)", meminfo).group(1)) // 1024
    swap_free = int(re.search(r"SwapFree:\s+(\d+)", meminfo).group(1)) // 1024
    return {
        "load1": load1, "load5": load5, "load15": load15,
        "ram_available_mb": hw["ram_available_mb"],
        "swap_used_mb": swap_total - swap_free,
    }


def aggregate(records: list[dict]) -> dict:
    ok = [r for r in records if "ERROR" not in r["tags"]]
    n = len(records)
    n_ok = len(ok)
    lat = sorted(r["latency_ms_client"] for r in ok)
    truncated = [r for r in ok if "TRUNCATED" in r["tags"]]
    empty = [r for r in records if "EMPTY" in r["tags"]]
    errors = [r for r in records if "ERROR" in r["tags"]]
    correct = [r for r in ok if "CORRECT" in r["tags"]]
    incorrect = [r for r in ok if "INCORRECT" in r["tags"]]

    def pct(p, arr):
        if not arr:
            return None
        k = (len(arr) - 1) * p
        f_, c_ = int(k), min(int(k) + 1, len(arr) - 1)
        return arr[f_] if f_ == c_ else arr[f_] + (arr[c_] - arr[f_]) * (k - f_)

    by_cat: dict[str, dict] = {}
    for cat in sorted({r["category"] for r in records}):
        cat_recs = [r for r in records if r["category"] == cat]
        cat_ok = [r for r in cat_recs if "ERROR" not in r["tags"]]
        cat_trunc = [r for r in cat_ok if "TRUNCATED" in r["tags"]]
        by_cat[cat] = {
            "n": len(cat_recs),
            "truncation_rate_pct": round(100 * len(cat_trunc) / len(cat_ok), 1) if cat_ok else None,
        }

    return {
        "n_total": n, "n_success": n_ok,
        "success_rate_pct": round(100 * n_ok / n, 1) if n else None,
        "error_rate_pct": round(100 * len(errors) / n, 1) if n else None,
        "empty_rate_pct": round(100 * len(empty) / n, 1) if n else None,
        "truncation_rate_pct": round(100 * len(truncated) / n_ok, 1) if n_ok else None,
        "correctness_pct_sur_prompts_verifiables": round(100 * len(correct) / (len(correct) + len(incorrect)), 1) if (correct or incorrect) else None,
        "latency_ms_mean": round(statistics.mean(lat), 1) if lat else None,
        "latency_ms_median": round(statistics.median(lat), 1) if lat else None,
        "latency_ms_stdev": round(statistics.stdev(lat), 1) if len(lat) > 1 else (0.0 if lat else None),
        "latency_ms_min": min(lat) if lat else None,
        "latency_ms_max": max(lat) if lat else None,
        "latency_ms_p95": round(pct(0.95, lat), 1) if lat else None,
        "response_len_words_mean": round(statistics.mean([r["response_len_words"] for r in ok]), 1) if ok else None,
        "by_category": by_cat,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["before", "after"], required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--num-predict-hint", type=int, default=0,
                     help="Valeur ollama_num_predict effective, utilisee uniquement pour l'heuristique de troncature (jamais interrogee en direct).")
    ap.add_argument("--load-avg-threshold", type=float, default=4.0)
    args = ap.parse_args()

    prompts = BEFORE_PROMPTS if args.phase == "before" else AFTER_PROMPTS

    if not API_KEY:
        sys.exit("NERON_API_KEY absente de l'environnement — impossible de tester la vraie prod.")

    health_before = system_snapshot()
    print(f"=== V5 phase={args.phase} — sante avant : {health_before}")
    if health_before["load1"] > args.load_avg_threshold:
        sys.exit(f"[ARRET PROPRE] load1={health_before['load1']:.2f} > seuil {args.load_avg_threshold} — abandon avant de commencer.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / f"raw_v5_{args.phase}_{ts}.jsonl"

    warmup_count = 0
    warmup_success = 0
    warmup_failure = 0
    if args.warmup:
        print(f"--- Warm-up ({args.warmup} appels) ---")
        for i in range(args.warmup):
            rec = call_generate(prompts[0]["prompt"], args.timeout)
            warmup_count += 1
            if rec["error"]:
                warmup_failure += 1
            else:
                warmup_success += 1
            print(f"  warmup {i+1}/{args.warmup} : {rec['latency_ms_client']}ms model_used={rec.get('model_used')} error={rec['error']}")

    print(f"\n=== Mesures reelles : {len(prompts)} prompts x {args.reps} reps = {len(prompts)*args.reps} appels ===")
    records = []
    health_samples = [health_before]
    with open(raw_path, "a") as fh:
        for pi, p in enumerate(prompts):
            for run_idx in range(1, args.reps + 1):
                if pi % 5 == 0 and run_idx == 1:
                    h = system_snapshot()
                    health_samples.append(h)
                    if h["load1"] > args.load_avg_threshold:
                        print(f"[PAUSE SANTE] load1={h['load1']:.2f} > seuil — pause 30s")
                        time.sleep(30)
                rec = call_generate(p["prompt"], args.timeout)
                rec["tags"] = classify_response(rec["response_text"], rec["error"], args.num_predict_hint, p["expected"])
                rec.update({
                    "phase": args.phase, "prompt_id": p["id"], "category": p["cat"], "prompt": p["prompt"],
                    "run_idx": run_idx, "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                records.append(rec)
                err_str = f" ERREUR: {rec['error']}" if rec["error"] else ""
                print(f"  [{p['id']:4}] run{run_idx} {rec['latency_ms_client']:>7}ms "
                      f"{'+'.join(rec['tags']):<20} model={rec.get('model_used')}{err_str}")

    health_after = system_snapshot()
    print(f"\n=== Sante apres : {health_after}")

    summary = aggregate(records)
    summary["warmup_count"] = warmup_count
    summary["warmup_success"] = warmup_success
    summary["warmup_failure"] = warmup_failure
    summary["health_before"] = health_before
    summary["health_after"] = health_after
    summary["health_samples"] = health_samples

    summary_json_path = RESULTS_DIR / f"summary_v5_{args.phase}_{ts}.json"
    summary_csv_path = RESULTS_DIR / f"summary_v5_{args.phase}_{ts}.csv"
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    with open(summary_csv_path, "w", newline="") as f:
        flat = {k: v for k, v in summary.items() if not isinstance(v, (dict, list))}
        w = csv.DictWriter(f, fieldnames=list(flat.keys()))
        w.writeheader()
        w.writerow(flat)

    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\nRaw -> {raw_path}\nSummary -> {summary_json_path} / {summary_csv_path}")


if __name__ == "__main__":
    main()
