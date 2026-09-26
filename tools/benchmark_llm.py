#!/usr/bin/env python3
"""Benchmark comparatif de petits modeles locaux pour NeronLLM.

Compare plusieurs petits modeles Ollama (~1-9B) sur deux niveaux :
  - Niveau A : appel direct a l'API Ollama (/api/generate, streaming)
  - Niveau B : appel via l'API reelle de NeronLLM (/llm/generate),
               qui force le modele teste via `model_preference`.

Mesure uniquement ce qui est reellement observable. Une metrique non
disponible (ex: tokens/s cote NeronLLM, qui ne renvoie pas les stats
Ollama) est enregistree comme None / "N/A" — jamais devinee.

La qualite des reponses et le respect des instructions ne sont PAS
notes automatiquement par ce script (aucun juge LLM n'est invoque) :
les textes bruts sont sauvegardes pour relecture humaine, cf. rapport.

Usage :
    python tools/benchmark_llm.py
    python tools/benchmark_llm.py --models llama3.2:1b,qwen3:1.7b
    python tools/benchmark_llm.py --runs 5 --level a
    python tools/benchmark_llm.py --pull-missing
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ── Configuration ─────────────────────────────────────────────────────────

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
NERON_LLM_URL = os.getenv("NERON_LLM_URL", "http://127.0.1.2:8765").rstrip("/")
if not NERON_LLM_URL.endswith("/llm"):
    NERON_LLM_URL += "/llm"
API_KEY = os.getenv("NERON_API_KEY", "")

RESULTS_DIR = Path(__file__).parent / "benchmark_results"

# Modeles curates pour Neron (baseline + candidats + gamme superieure a
# titre de comparaison). "risky" = deja documente dans neron.yaml comme
# trop volumineux pour la RAM de cette machine (7.2 Gi, swap deja plein) :
# testes un par un, avec pause et dechargement explicite entre chacun.
CURATED_MODELS: dict[str, dict] = {
    "llama3.2:1b":        {"tier": "small", "pull_if_missing": True},
    "qwen2.5:1.5b":       {"tier": "small", "pull_if_missing": True},
    "qwen3:1.7b":         {"tier": "small", "pull_if_missing": True},
    "gemma3:1b":          {"tier": "small", "pull_if_missing": True},
    "smollm2:1.7b":       {"tier": "small", "pull_if_missing": True},
    "qwen3:4b-instruct":  {"tier": "risky", "pull_if_missing": False},
    "qwen3.5:4b":         {"tier": "risky", "pull_if_missing": False},
    "qwen3.5:9b":         {"tier": "risky", "pull_if_missing": False},
}

BASELINE_MODEL = "llama3.2:1b"

# Fallback si un modele curate n'est plus disponible sur le registre Ollama.
FALLBACK_MODELS: dict[str, list[str]] = {
    "llama3.2:1b":  ["llama3.2:1b-instruct-q4_K_M"],
    "qwen2.5:1.5b": ["qwen2.5:1.5b-instruct"],
    "gemma3:1b":    ["gemma3:1b-it-qat"],
    "smollm2:1.7b": ["smollm2:1.7b-instruct"],
}

# ── Jeu de tests standardise (mission, section 5) ────────────────────────

TESTS: list[dict] = [
    {"id": "t1_factuelle",     "task_type": "chat", "prompt": "Quelle est la capitale de la France ?"},
    {"id": "t2_calcul",        "task_type": "chat", "prompt": "Combien font 27 + 35 ?"},
    {"id": "t3_comprehension", "task_type": "chat", "prompt": "Je pars a 8h30 et mon trajet dure 1h45. A quelle heure arrive-je ?"},
    {"id": "t4_instruction",   "task_type": "chat", "prompt": "Reponds uniquement par le mot : OK"},
    {"id": "t5_concision",     "task_type": "chat", "prompt": "Explique ce qu'est Linux en deux phrases maximum."},
    {"id": "t6_contexte",      "task_type": "chat", "prompt": (
        "Neron est un assistant personnel local.\n"
        "Il peut utiliser plusieurs services et outils.\n"
        "Il doit privilegier des reponses courtes et precises.\n"
        "Quel doit etre son role principal ?"
    )},
    {"id": "t7_raisonnement",  "task_type": "reasoning", "prompt": (
        "Pierre a 10 pommes.\nIl en donne 3 a Paul puis achete 5 pommes.\n"
        "Combien lui reste-t-il de pommes ?"
    )},
    {"id": "t8_francais",      "task_type": "chat", "prompt": "Explique simplement ce qu'est une API REST."},
    {"id": "t9_instruction_stricte", "task_type": "chat", "prompt": (
        "Reponds uniquement avec un nombre.\nCombien font 12 x 8 ?"
    )},
    {"id": "t10_simulation",  "task_type": "chat", "prompt": (
        "Utilisateur : Quelle heure est-il ?\n"
        "Tu es Neron, un assistant personnel.\n"
        "Repond de maniere concise et naturelle."
    )},
]


# ── Environnement ─────────────────────────────────────────────────────────

def check_ollama_running() -> str:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/version", timeout=5.0)
        r.raise_for_status()
        return r.json().get("version", "inconnue")
    except Exception as exc:
        sys.exit(f"Ollama injoignable sur {OLLAMA_URL} : {exc}")


def get_hardware_info() -> dict:
    info: dict = {}
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        info["cpu"] = "N/A"
    try:
        info["cpu_count"] = os.cpu_count()
    except Exception:
        info["cpu_count"] = None
    try:
        mem_total = mem_avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) // 1024
        info["ram_total_mb"] = mem_total
        info["ram_available_mb"] = mem_avail
    except OSError:
        info["ram_total_mb"] = info["ram_available_mb"] = None
    try:
        subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        info["gpu"] = "NVIDIA GPU detected (nvidia-smi present)"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info["gpu"] = "Aucun GPU detecte (pas de nvidia-smi)"
    return info


def get_installed_models() -> dict[str, dict]:
    r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10.0)
    r.raise_for_status()
    out = {}
    for m in r.json().get("models", []):
        out[m["name"]] = {"size_bytes": m.get("size"), "modified_at": m.get("modified_at")}
    return out


def get_model_details(model: str) -> dict:
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": model}, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        details = data.get("details", {})
        return {
            "family": details.get("family", "N/A"),
            "parameter_size": details.get("parameter_size", "N/A"),
            "quantization_level": details.get("quantization_level", "N/A"),
            "format": details.get("format", "N/A"),
        }
    except Exception as exc:
        return {"family": "N/A", "parameter_size": "N/A", "quantization_level": "N/A", "format": "N/A", "error": str(exc)}


def resolve_model_name(requested: str, installed: dict[str, dict]) -> str | None:
    """Retourne le nom de modele reellement disponible (avec fallback)."""
    if requested in installed:
        return requested
    for alt in FALLBACK_MODELS.get(requested, []):
        if alt in installed:
            return alt
    return None


def pull_model(model: str) -> bool:
    print(f"  -> pull {model} ...")
    candidates = [model] + FALLBACK_MODELS.get(model, [])
    for candidate in candidates:
        proc = subprocess.run(["ollama", "pull", candidate], capture_output=False)
        if proc.returncode == 0:
            if candidate != model:
                print(f"     '{model}' indisponible, utilise '{candidate}' a la place.")
            return True
        print(f"     echec pull '{candidate}' (code {proc.returncode})")
    return False


def unload_model(model: str) -> None:
    """Decharge immediatement le modele de la RAM (keep_alive=0)."""
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=30.0,
        )
    except Exception:
        pass


def get_loaded_model_memory(model: str) -> int | None:
    """Interroge /api/ps pour la RAM/VRAM reellement occupee par le modele charge."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=10.0)
        r.raise_for_status()
        for m in r.json().get("models", []):
            if m.get("name") == model or m.get("model") == model:
                return m.get("size")
        return None
    except Exception:
        return None


# ── Niveau A : Ollama direct ─────────────────────────────────────────────

def run_ollama_direct(model: str, prompt: str, timeout_s: float, max_tokens: int) -> dict:
    """Un appel streaming a /api/generate. Renvoie un dict de mesures brutes."""
    t0 = time.monotonic()
    ttft = None
    full_text = []
    final_stats: dict = {}
    error = None
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "10m",
        "think": False,
    }
    # max_tokens <= 0 reproduit exactement le comportement de
    # llm/providers/ollama.py : `if self._num_predict > 0` — sinon aucune
    # cle options.num_predict n'est envoyee et Ollama utilise son propre
    # defaut (generation non plafonnee), PAS "0 token genere".
    if max_tokens > 0:
        payload["options"] = {"num_predict": max_tokens}
    try:
        with httpx.stream(
            "POST",
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=timeout_s,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                chunk = obj.get("response", "")
                if chunk and ttft is None:
                    ttft = time.monotonic() - t0
                if chunk:
                    full_text.append(chunk)
                if obj.get("done"):
                    final_stats = obj
    except httpx.TimeoutException:
        error = f"timeout > {timeout_s}s"
    except Exception as exc:
        error = str(exc)

    wall_s = time.monotonic() - t0
    ns = 1e9
    return {
        "level": "A_ollama_direct",
        "model": model,
        "error": error,
        "response_text": "".join(full_text) if not error else None,
        "wall_duration_s": wall_s,
        "time_to_first_token_s": ttft,
        "load_duration_s": (final_stats.get("load_duration") / ns) if final_stats.get("load_duration") is not None else None,
        "total_duration_s": (final_stats.get("total_duration") / ns) if final_stats.get("total_duration") is not None else None,
        "prompt_eval_count": final_stats.get("prompt_eval_count"),
        "prompt_eval_duration_s": (final_stats.get("prompt_eval_duration") / ns) if final_stats.get("prompt_eval_duration") is not None else None,
        "eval_count": final_stats.get("eval_count"),
        "eval_duration_s": (final_stats.get("eval_duration") / ns) if final_stats.get("eval_duration") is not None else None,
    }


# ── Niveau B : NeronLLM reel ──────────────────────────────────────────────

def run_neron_llm(model: str, task_type: str, prompt: str, timeout_s: float) -> dict:
    """Un appel a POST /llm/generate, en forcant le modele via model_preference."""
    if not API_KEY:
        return {
            "level": "B_neron_llm", "model": model, "error": "NERON_API_KEY absente de l'environnement",
            "response_text": None, "wall_duration_s": None, "latency_ms_reported": None,
        }
    t0 = time.monotonic()
    error = None
    result_text = None
    latency_ms = None
    try:
        r = httpx.post(
            f"{NERON_LLM_URL}/generate",
            json={"task_type": task_type, "prompt": prompt, "model_preference": model},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=timeout_s,
        )
        wall_s = time.monotonic() - t0
        if r.status_code != 200:
            error = f"HTTP {r.status_code}: {r.text[:200]}"
        else:
            data = r.json()
            result_text = data.get("result")
            latency_ms = data.get("latency_ms")
            used = data.get("model_used")
            if used and used != model:
                error = f"modele reellement utilise = '{used}' (fallback, pas '{model}')"
    except httpx.TimeoutException:
        wall_s = time.monotonic() - t0
        error = f"timeout > {timeout_s}s"
    except Exception as exc:
        wall_s = time.monotonic() - t0
        error = str(exc)

    return {
        "level": "B_neron_llm",
        "model": model,
        "error": error,
        "response_text": result_text,
        "wall_duration_s": wall_s,
        "latency_ms_reported": latency_ms,
        # Non disponible via l'API NeronLLM (/llm/generate ne renvoie pas les
        # stats Ollama) : jamais devine, toujours explicite.
        "time_to_first_token_s": None,
        "load_duration_s": None,
        "prompt_eval_count": None,
        "prompt_eval_duration_s": None,
        "eval_count": None,
        "eval_duration_s": None,
    }


# ── Boucle de benchmark ────────────────────────────────────────────────────

def benchmark_model(
    model: str,
    levels: list[str],
    runs: int,
    warmup: int,
    timeout_s: float,
    max_tokens: int,
    results_fh,
    tests: list[dict] | None = None,
) -> list[dict]:
    records = []
    for test in (tests if tests is not None else TESTS):
        total_attempts = warmup + runs
        for level in levels:
            for i in range(total_attempts):
                is_warmup = i < warmup
                run_idx = i - warmup + 1  # 1..runs pour les mesures reelles
                if level == "a":
                    rec = run_ollama_direct(model, test["prompt"], timeout_s, max_tokens)
                else:
                    rec = run_neron_llm(model, test["task_type"], test["prompt"], timeout_s)
                rec.update({
                    "test_id": test["id"],
                    "is_warmup": is_warmup,
                    "run_idx": None if is_warmup else run_idx,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                status = "WARMUP" if is_warmup else f"run {run_idx}/{runs}"
                dur = rec.get("wall_duration_s")
                dur_str = f"{dur:.1f}s" if dur is not None else "?"
                err_str = f" ERREUR: {rec['error']}" if rec.get("error") else ""
                print(f"    [{level}] {test['id']:<22} {status:<10} {dur_str}{err_str}")
                records.append(rec)
                results_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                results_fh.flush()
    return records


def aggregate(records: list[dict]) -> list[dict]:
    """Moyennes/ecarts-types par (model, level, test_id), warmup exclu."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in records:
        if r.get("is_warmup"):
            continue
        key = (r["model"], r["level"], r["test_id"])
        groups[key].append(r)

    summary = []
    for (model, level, test_id), recs in groups.items():
        ok = [r for r in recs if not r.get("error")]
        n_total = len(recs)
        n_ok = len(ok)

        def mean_of(field):
            vals = [r[field] for r in ok if r.get(field) is not None]
            return statistics.mean(vals) if vals else None

        def stdev_of(field):
            vals = [r[field] for r in ok if r.get(field) is not None]
            return statistics.stdev(vals) if len(vals) > 1 else 0.0 if vals else None

        eval_count_mean = mean_of("eval_count")
        eval_dur_mean = mean_of("eval_duration_s")
        prompt_count_mean = mean_of("prompt_eval_count")
        prompt_dur_mean = mean_of("prompt_eval_duration_s")

        gen_tps = (eval_count_mean / eval_dur_mean) if (eval_count_mean and eval_dur_mean) else None
        prompt_tps = (prompt_count_mean / prompt_dur_mean) if (prompt_count_mean and prompt_dur_mean) else None

        summary.append({
            "model": model,
            "level": level,
            "test_id": test_id,
            "n_runs": n_total,
            "n_success": n_ok,
            "stability_pct": round(100 * n_ok / n_total, 1) if n_total else None,
            "wall_duration_s_mean": mean_of("wall_duration_s"),
            "wall_duration_s_stdev": stdev_of("wall_duration_s"),
            "time_to_first_token_s_mean": mean_of("time_to_first_token_s"),
            "load_duration_s_mean": mean_of("load_duration_s"),
            "eval_count_mean": eval_count_mean,
            "generation_tokens_per_second": gen_tps,
            "prompt_tokens_per_second": prompt_tps,
            "latency_ms_reported_mean": mean_of("latency_ms_reported"),
        })
    return summary


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=str, default=None, help="Liste separee par virgules, defaut = jeu curate complet.")
    ap.add_argument("--runs", type=int, default=3, help="Repetitions mesurees par test (defaut 3).")
    ap.add_argument("--warmup", type=int, default=1, help="Repetitions warmup non comptees (defaut 1).")
    ap.add_argument("--level", choices=["a", "b", "both"], default="both", help="Niveau A (Ollama direct), B (NeronLLM), ou both.")
    ap.add_argument("--pull-missing", action="store_true", help="Pull les modeles curates absents avant le benchmark.")
    ap.add_argument("--timeout", type=float, default=150.0, help="Timeout par appel en secondes (defaut 150).")
    ap.add_argument("--max-tokens", type=int, default=300, help="Plafond num_predict cote Ollama direct (defaut 300, protege le CPU).")
    ap.add_argument("--pause-between-models", type=float, default=10.0, help="Pause en secondes entre deux modeles (defaut 10).")
    ap.add_argument("--skip-risky", action="store_true", help="Ignore les modeles marques 'risky' (deja documentes trop gros pour la RAM).")
    ap.add_argument("--test-ids", type=str, default=None, help="Sous-ensemble de tests (id separes par virgules), defaut = les 10 tests.")
    args = ap.parse_args()

    selected_tests = TESTS
    if args.test_ids:
        wanted = {t.strip() for t in args.test_ids.split(",")}
        selected_tests = [t for t in TESTS if t["id"] in wanted]
        unknown = wanted - {t["id"] for t in TESTS}
        if unknown:
            sys.exit(f"test-ids inconnus : {', '.join(unknown)}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / f"raw_{ts}.jsonl"
    summary_json_path = RESULTS_DIR / f"summary_{ts}.json"
    summary_csv_path = RESULTS_DIR / f"summary_{ts}.csv"
    meta_path = RESULTS_DIR / f"meta_{ts}.json"

    print("=== Verification environnement ===")
    ollama_version = check_ollama_running()
    hw = get_hardware_info()
    print(f"Ollama version : {ollama_version}")
    print(f"CPU : {hw['cpu']} ({hw['cpu_count']} coeurs)")
    print(f"RAM : {hw['ram_total_mb']} MiB total, {hw['ram_available_mb']} MiB disponible")
    print(f"GPU : {hw['gpu']}")

    requested_models = (
        [m.strip() for m in args.models.split(",")] if args.models
        else list(CURATED_MODELS.keys())
    )
    if args.skip_risky:
        requested_models = [m for m in requested_models if CURATED_MODELS.get(m, {}).get("tier") != "risky"]

    if args.pull_missing:
        print("\n=== Pull des modeles manquants ===")
        installed = get_installed_models()
        for m in requested_models:
            if m not in installed and CURATED_MODELS.get(m, {}).get("pull_if_missing", True):
                pull_model(m)

    installed = get_installed_models()
    print("\n=== Modeles a tester ===")
    resolved: dict[str, str] = {}
    for m in requested_models:
        actual = resolve_model_name(m, installed)
        if actual is None:
            print(f"  [ABSENT] {m} — ni le modele ni un fallback ne sont installes (utilisez --pull-missing).")
            continue
        details = get_model_details(actual)
        size_mb = installed[actual]["size_bytes"] / (1024 * 1024) if installed[actual]["size_bytes"] else None
        resolved[m] = actual
        tier = CURATED_MODELS.get(m, {}).get("tier", "?")
        print(f"  [{tier:5}] {m:22} -> {actual:22} params={details['parameter_size']:<8} quant={details['quantization_level']:<10} taille={size_mb:.0f} MB" if size_mb else f"  {m} -> {actual}")

    if not resolved:
        sys.exit("Aucun modele disponible a tester.")

    levels = ["a", "b"] if args.level == "both" else [args.level]
    if "b" in levels and not API_KEY:
        print("\n[ATTENTION] NERON_API_KEY absente : le niveau B (NeronLLM reel) sera enregistre en erreur pour chaque appel.")

    meta = {
        "timestamp_utc": ts,
        "ollama_version": ollama_version,
        "hardware": hw,
        "models_requested": requested_models,
        "models_resolved": resolved,
        "runs": args.runs,
        "warmup": args.warmup,
        "levels": levels,
        "max_tokens": args.max_tokens,
        "timeout_s": args.timeout,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n=== Benchmark ({len(resolved)} modele(s), {len(selected_tests)} tests, "
          f"{args.warmup} warmup + {args.runs} mesures, niveaux={levels}) ===")
    print(f"Resultats bruts -> {raw_path}")

    all_records = []
    with open(raw_path, "w") as fh:
        for i, (requested, actual) in enumerate(resolved.items()):
            tier = CURATED_MODELS.get(requested, {}).get("tier", "?")
            print(f"\n--- Modele {i+1}/{len(resolved)} : {actual} (tier={tier}) ---")
            if tier == "risky":
                mem = get_hardware_info()
                print(f"  [garde-fou] RAM disponible avant chargement : {mem['ram_available_mb']} MiB")
            recs = benchmark_model(actual, levels, args.runs, args.warmup, args.timeout, args.max_tokens, fh, tests=selected_tests)
            all_records.extend(recs)
            unload_model(actual)
            if i < len(resolved) - 1:
                print(f"  (dechargement du modele, pause {args.pause_between_models:.0f}s avant le suivant)")
                time.sleep(args.pause_between_models)

    print("\n=== Agregation ===")
    summary = aggregate(all_records)
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    fieldnames = list(summary[0].keys()) if summary else []
    with open(summary_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)

    print(f"Resume JSON -> {summary_json_path}")
    print(f"Resume CSV  -> {summary_csv_path}")
    print(f"Metadonnees -> {meta_path}")
    print("\nTerminé. La qualite/instruction-following n'est PAS notee automatiquement : "
          "relire les 'response_text' dans le fichier raw pour noter chaque modele.")


if __name__ == "__main__":
    main()
