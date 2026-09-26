#!/usr/bin/env python3
"""Validation V3 — comparaison reelle llama3.2:1b vs qwen2.5:1.5b a
num_predict=64 identique, via le VRAI POST /llm/generate.

Contrainte de la mission : ne jamais modifier neron.yaml ni le service
neron@llm.service en production. Mecanisme retenu (identique en esprit a
V2, mais plus fidele a "l'API reelle" cette fois) : une instance FastAPI
jetable (tools/llm_v3_test_service.py) qui monte le VRAI router
server/llm/api/routes.py (meme code que la prod, meme contrat
POST /llm/generate), sur un port dedie, avec une copie temporaire de
neron.yaml (seul ollama_num_predict=64 differe). Pas de RegistryClient
(pas de create_service_app), pour ne jamais entrer en collision avec le
service llm reellement enregistre aupres du registry de Core.

Usage :
    python tools/benchmark_llm_v3.py
    python tools/benchmark_llm_v3.py --reps 5 --load-avg-threshold 4
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_llm import (  # noqa: E402
    RESULTS_DIR,
    check_ollama_running,
    get_hardware_info,
    get_installed_models,
    get_model_details,
)

NERON_ROOT = Path(__file__).resolve().parents[1]
NERON_YAML_PATH = NERON_ROOT / "neron.yaml"
TEST_SERVICE = Path(__file__).resolve().parent / "llm_v3_test_service.py"
TMP_CONFIG_DIR = Path(tempfile.gettempdir()) / "neron_bench_v3_configs"

MODEL_A = "llama3.2:1b"   # baseline
MODEL_B = "qwen2.5:1.5b"  # candidat
NUM_PREDICT = 64
TEST_PORT = 8766
TEST_HOST = "127.0.0.1"

# ── Jeu de tests V3 (mission section 5-6) ─────────────────────────────────

PROMPTS: list[dict] = [
    # Categorie A — questions tres courtes
    {"id": "A1", "cat": "A_courte", "prompt": "Quelle est la capitale de la France ?"},
    {"id": "A2", "cat": "A_courte", "prompt": "Combien font 12 x 8 ?"},
    {"id": "A3", "cat": "A_courte", "prompt": "Quel jour sommes-nous ?"},
    {"id": "A4", "cat": "A_courte", "prompt": "Quelle heure est-il ?"},
    # Categorie B — questions naturelles
    {"id": "B1", "cat": "B_naturelle", "prompt": "Explique-moi simplement ce qu'est Linux."},
    {"id": "B2", "cat": "B_naturelle", "prompt": "A quoi sert une API REST ?"},
    {"id": "B3", "cat": "B_naturelle", "prompt": "Quelle est la difference entre une IA et un LLM ?"},
    # Categorie C — instructions strictes
    {"id": "C1", "cat": "C_stricte", "prompt": "Reponds uniquement par OK."},
    {"id": "C2", "cat": "C_stricte", "prompt": "Reponds uniquement avec un nombre.\nCombien font 25 + 17 ?"},
    {"id": "C3", "cat": "C_stricte", "prompt": "Donne-moi trois mots pour decrire Linux."},
    # Categorie D — raisonnement simple
    {"id": "D1", "cat": "D_raisonnement", "prompt": "J'ai 10 pommes. J'en donne 3 puis j'en achete 5. Combien m'en reste-t-il ?"},
    {"id": "D2", "cat": "D_raisonnement", "prompt": "Je pars a 8h30 et mon trajet dure 1h45. A quelle heure arrive-je ?"},
    {"id": "D3", "cat": "D_raisonnement", "prompt": "Un film commence a 20h30 et dure 2h15. A quelle heure se termine-t-il ?"},
    # Categorie E — contexte Neron
    {"id": "E1", "cat": "E_contexte", "prompt": (
        "Tu es Neron, un assistant personnel local.\n"
        "Tu dois repondre de maniere concise, precise et naturelle.\n"
        "Quel est ton role ?"
    )},
    {"id": "E2", "cat": "E_contexte", "prompt": (
        "Tu es Neron.\n"
        "L'utilisateur te demande une information simple.\n"
        "Privilegie une reponse courte plutot qu'une longue explication.\n"
        "Explique ce qu'est Docker."
    )},
    {"id": "E3", "cat": "E_contexte", "prompt": (
        "Tu es un assistant personnel.\n"
        "Si une question est simple, reponds directement sans ajouter d'informations inutiles.\n"
        "Pourquoi utilise-t-on Linux sur un serveur ?"
    )},
    # Tests de longueur (section 6)
    {"id": "L1", "cat": "L_longueur", "prompt": "Explique-moi les principales differences entre Linux et Windows en quelques points."},
    {"id": "L2", "cat": "L_longueur", "prompt": "Explique-moi simplement comment fonctionne un serveur web."},
    {"id": "L3", "cat": "L_longueur", "prompt": "Explique le fonctionnement general d'un LLM a quelqu'un qui ne connait pas l'intelligence artificielle."},
]


# ── Config temporaire + service jetable ───────────────────────────────────

def make_temp_config() -> Path:
    TMP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(NERON_YAML_PATH.read_text())
    cfg["llm"]["ollama_num_predict"] = NUM_PREDICT
    fd, path_str = tempfile.mkstemp(prefix="neron_v3_", suffix=".yaml", dir=TMP_CONFIG_DIR)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    return Path(path_str)


def cleanup_temp_configs() -> None:
    if not TMP_CONFIG_DIR.exists():
        return
    for f in TMP_CONFIG_DIR.glob("*"):
        f.unlink(missing_ok=True)
    try:
        TMP_CONFIG_DIR.rmdir()
    except OSError:
        pass


def start_test_service(tmp_cfg: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["NERON_CONFIG"] = str(tmp_cfg)
    env.pop("NERON_API_KEY", None)  # auth desactivee sur l'instance jetable, non exposee au reseau
    proc = subprocess.Popen(
        [sys.executable, str(TEST_SERVICE), "--host", TEST_HOST, "--port", str(TEST_PORT)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return proc


def wait_for_ready(timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    url = f"http://{TEST_HOST}:{TEST_PORT}/v3_ready"
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=3.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


# ── Sante systeme ──────────────────────────────────────────────────────

def system_health() -> dict:
    load1, load5, load15 = os.getloadavg()
    hw = get_hardware_info()
    return {"load1": load1, "load5": load5, "load15": load15,
            "ram_available_mb": hw["ram_available_mb"]}


def preflight_checks() -> dict:
    print("=== Pre-vol V3 ===")
    report = {}

    ollama_version = check_ollama_running()
    print(f"Ollama : OK (version {ollama_version})")
    report["ollama"] = ollama_version

    try:
        r = httpx.get("http://127.0.1.2:8765/llm/health", timeout=5.0)
        report["neron_llm_prod_health"] = r.json()
        print(f"NeronLLM (prod, non touche) : {r.json()}")
    except Exception as exc:
        report["neron_llm_prod_health"] = f"injoignable: {exc}"
        print(f"[ATTENTION] NeronLLM prod injoignable : {exc}")

    try:
        out = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        neron_services = [l.split()[0] for l in out.splitlines() if "neron" in l.lower()]
        report["neron_services_running"] = neron_services
        print(f"Services NeronOS actifs : {len(neron_services)}")
    except Exception as exc:
        report["neron_services_running"] = f"erreur: {exc}"

    hw = get_hardware_info()
    load1, load5, load15 = os.getloadavg()
    report["hardware"] = hw
    report["load_avg"] = {"1min": load1, "5min": load5, "15min": load15}
    print(f"RAM dispo : {hw['ram_available_mb']} MiB | load avg : {load1:.2f}/{load5:.2f}/{load15:.2f}")

    other_bench = subprocess.run(
        ["pgrep", "-f", "benchmark_llm"], capture_output=True, text=True,
    ).stdout.strip()
    # Exclut ce process ET son parent direct : quand ce script est lance via
    # `bash -c '... python benchmark_llm_v3.py ...'`, le wrapper bash porte
    # aussi la chaine "benchmark_llm" dans sa propre ligne de commande et
    # matchait `pgrep -f`, se faisant passer pour "un autre benchmark".
    excluded_pids = {str(os.getpid()), str(os.getppid())}
    other_pids = [p for p in other_bench.splitlines() if p not in excluded_pids]
    report["other_benchmarks_running"] = other_pids
    if other_pids:
        print(f"[ATTENTION] Autres process benchmark_llm* detectes : {other_pids}")
    else:
        print("Aucun autre benchmark actif.")

    return report


# ── Execution des appels ──────────────────────────────────────────────

def call_generate(model: str, prompt: str, timeout_s: float) -> dict:
    t0 = time.monotonic()
    error = None
    result_text = None
    latency_ms_api = None
    model_used = None
    status_code = None
    try:
        r = httpx.post(
            f"http://{TEST_HOST}:{TEST_PORT}/llm/generate",
            json={"task_type": "chat", "prompt": prompt, "model_preference": model},
            timeout=timeout_s,
        )
        status_code = r.status_code
        wall_s = time.monotonic() - t0
        if r.status_code == 200:
            data = r.json()
            result_text = data.get("result")
            latency_ms_api = data.get("latency_ms")
            model_used = data.get("model_used")
            if model_used and model_used != model:
                error = f"modele reellement utilise = '{model_used}' (fallback, pas '{model}')"
        else:
            error = f"HTTP {r.status_code}: {r.text[:200]}"
    except httpx.TimeoutException:
        wall_s = time.monotonic() - t0
        error = f"timeout > {timeout_s}s"
    except Exception as exc:
        wall_s = time.monotonic() - t0
        error = str(exc)

    return {
        "model_requested": model,
        "model_used": model_used,
        "num_predict": NUM_PREDICT,
        "http_status": status_code,
        "error": error,
        "response_text": result_text,
        "response_len_chars": len(result_text) if result_text else 0,
        "response_len_words": len(result_text.split()) if result_text else 0,
        "latency_ms_client": round(wall_s * 1000),
        "latency_ms_api_reported": latency_ms_api,
        "eval_count": "N/A",  # non fourni par /llm/generate — jamais devine
    }


def build_interleaved_order(n_reps: int, seed: int) -> list[str]:
    """n_reps x A + n_reps x B, ordre entrelace deterministe (pas bloc par bloc)."""
    seq = [MODEL_A] * n_reps + [MODEL_B] * n_reps
    rnd = random.Random(seed)
    rnd.shuffle(seq)
    return seq


# ── Agregation ─────────────────────────────────────────────────────────

def classify_truncation(text: str | None, num_predict: int) -> str:
    if not text:
        return "INCOHERENTE"
    stripped = text.rstrip()
    ends_clean = stripped.endswith((".", "!", "?", "»", '"', ":", "OK"))
    words = len(stripped.split())
    if not ends_clean and words >= max(3, int(num_predict / 1.85) - 5):
        return "TRONQUEE"
    if not ends_clean and words < 3:
        return "INCOHERENTE"
    if words > 120:
        return "TROP_LONGUE"
    return "COMPLETE"


def aggregate(raw_path: Path) -> dict:
    by_model: dict[str, list[dict]] = {MODEL_A: [], MODEL_B: []}
    with open(raw_path) as f:
        for line in f:
            r = json.loads(line)
            by_model[r["model_requested"]].append(r)

    summary = {}
    for model, recs in by_model.items():
        n = len(recs)
        ok = [r for r in recs if not r.get("error")]
        n_ok = len(ok)
        lat = sorted(r["latency_ms_client"] for r in ok)
        trunc = [r for r in ok if r.get("truncation_status") == "TRONQUEE"]

        def pct(p):
            if not lat:
                return None
            k = (len(lat) - 1) * p
            f_, c_ = int(k), min(int(k) + 1, len(lat) - 1)
            if f_ == c_:
                return lat[f_]
            return lat[f_] + (lat[c_] - lat[f_]) * (k - f_)

        summary[model] = {
            "n_total": n,
            "n_success": n_ok,
            "success_rate_pct": round(100 * n_ok / n, 1) if n else None,
            "error_rate_pct": round(100 * (n - n_ok) / n, 1) if n else None,
            "latency_ms_mean": round(statistics.mean(lat), 1) if lat else None,
            "latency_ms_median": round(statistics.median(lat), 1) if lat else None,
            "latency_ms_stdev": round(statistics.stdev(lat), 1) if len(lat) > 1 else (0.0 if lat else None),
            "latency_ms_min": min(lat) if lat else None,
            "latency_ms_max": max(lat) if lat else None,
            "latency_ms_p95": round(pct(0.95), 1) if lat else None,
            "truncation_rate_pct": round(100 * len(trunc) / n_ok, 1) if n_ok else None,
            "response_len_words_mean": round(statistics.mean([r["response_len_words"] for r in ok]), 1) if ok else None,
        }
    return summary


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--load-avg-threshold", type=float, default=4.0,
                     help="Si load1 > seuil, le test se met en pause jusqu'a stabilisation.")
    ap.add_argument("--max-pause-s", type=float, default=1800.0,
                     help="Abandon si la pause de sante cumulee depasse ce seuil.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / f"raw_{ts}.jsonl"
    meta_path = RESULTS_DIR / f"meta_{ts}.json"
    summary_json_path = RESULTS_DIR / f"summary_{ts}.json"
    summary_csv_path = RESULTS_DIR / f"summary_{ts}.csv"

    preflight = preflight_checks()
    if preflight["other_benchmarks_running"]:
        sys.exit("Un autre benchmark_llm* tourne deja — abandon (mission section 4).")

    load1 = preflight["load_avg"]["1min"]
    if load1 > args.load_avg_threshold:
        print(f"\n[ARRET PROPRE] load1={load1:.2f} > seuil {args.load_avg_threshold} — "
              f"degradation systeme deja presente avant meme de commencer. "
              f"Abandon (mission section 4 : ne pas lancer sur un systeme deja degrade).")
        meta = {"timestamp_utc": ts, "aborted": True, "reason": "load_avg_too_high_preflight", "preflight": preflight}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str))
        sys.exit(1)

    tmp_cfg = make_temp_config()
    print(f"\n=== Config temporaire : {tmp_cfg} (num_predict={NUM_PREDICT}) ===")
    proc = start_test_service(tmp_cfg)
    total_pause = 0.0
    aborted_reason = None

    try:
        print("Demarrage de l'instance NeronLLM jetable...")
        if not wait_for_ready(60.0):
            aborted_reason = "instance_jetable_non_prete"
            print("[ARRET PROPRE] L'instance jetable n'a pas demarre a temps.")
        else:
            print("Instance prete.\n")

            details_a = get_model_details(MODEL_A)
            details_b = get_model_details(MODEL_B)
            print(f"Config A : {MODEL_A} ({details_a['parameter_size']}, {details_a['quantization_level']})")
            print(f"Config B : {MODEL_B} ({details_b['parameter_size']}, {details_b['quantization_level']})")

            meta = {
                "timestamp_utc": ts,
                "mission": "V3 validation reelle",
                "model_a_baseline": MODEL_A,
                "model_b_candidate": MODEL_B,
                "num_predict": NUM_PREDICT,
                "reps": args.reps,
                "seed": args.seed,
                "preflight": preflight,
                "test_service": "instance FastAPI jetable montant le vrai router server/llm/api/routes.py, "
                                 "SANS create_service_app (donc sans enregistrement au registry Core) — "
                                 "port dedie, config temporaire, aucun impact sur neron@llm.service.",
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str))

            with open(raw_path, "a") as fh:
                for pi, p in enumerate(PROMPTS):
                    order = build_interleaved_order(args.reps, seed=args.seed + pi)
                    print(f"\n--- {p['id']} [{p['cat']}] : {p['prompt'][:50]!r} — ordre {order} ---")
                    run_counts = {MODEL_A: 0, MODEL_B: 0}
                    for model in order:
                        health = system_health()
                        if health["load1"] > args.load_avg_threshold:
                            pause_start = time.monotonic()
                            print(f"    [PAUSE SANTE] load1={health['load1']:.2f} > {args.load_avg_threshold} "
                                  f"— attente stabilisation...")
                            while system_health()["load1"] > args.load_avg_threshold:
                                time.sleep(20)
                                total_pause += 20
                                if total_pause > args.max_pause_s:
                                    aborted_reason = "degradation_systeme_prolongee"
                                    break
                            if aborted_reason:
                                break
                            print(f"    [REPRISE] apres {time.monotonic() - pause_start:.0f}s de pause")
                        if aborted_reason:
                            break

                        run_counts[model] += 1
                        rec = call_generate(model, p["prompt"], args.timeout)
                        rec["truncation_status"] = classify_truncation(rec["response_text"], NUM_PREDICT)
                        rec.update({
                            "prompt_id": p["id"], "category": p["cat"], "prompt": p["prompt"],
                            "run_idx": run_counts[model],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        fh.flush()
                        status = "OK" if not rec["error"] else f"ERREUR: {rec['error']}"
                        print(f"    [{model:14}] run {run_counts[model]}/{args.reps} "
                              f"{rec['latency_ms_client']:>7}ms {rec['truncation_status']:<12} {status}")
                    if aborted_reason:
                        break

            if aborted_reason:
                print(f"\n[ARRET PROPRE] Raison : {aborted_reason}. Donnees partielles conservees dans {raw_path}.")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        tmp_cfg.unlink(missing_ok=True)
        cleanup_temp_configs()
        print("\nInstance jetable arretee, config temporaire supprimee.")

    if raw_path.exists() and raw_path.stat().st_size > 0:
        print("\n=== Agregation ===")
        summary = aggregate(raw_path)
        summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        rows = [{"model": m, **s} for m, s in summary.items()]
        with open(summary_csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nRaw -> {raw_path}\nSummary JSON -> {summary_json_path}\nSummary CSV -> {summary_csv_path}\nMeta -> {meta_path}")

    print("\nConfirmation : neron.yaml et neron@llm.service non modifies.")


if __name__ == "__main__":
    main()
