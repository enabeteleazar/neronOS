#!/usr/bin/env python3
"""V4 — recherche du num_predict optimal pour qwen2.5:1.5b.

Meme principe que V3 (vrai code NeronLLM, vrai POST /llm/generate, instance
FastAPI jetable sans RegistryClient), mais avec une difference structurelle :
`ollama_num_predict` est fige a la CONSTRUCTION du OllamaProvider (lu une
fois depuis la config), pas par requete. Pour respecter la consigne
d'entrelacer les valeurs de num_predict (section 8 de la mission) sans
redemarrer un service a chaque appel, on lance 5 instances jetables EN
PARALLELE, une par valeur de num_predict testee (64/80/96/128/160), chacune
sur son propre port avec sa propre config temporaire. Le test route chaque
appel vers le port correspondant a la valeur tiree pour ce tour. Les 5
instances tapent toutes sur le meme Ollama (qui serialise les generations
de toute facon, comme en production) — aucune ne touche neron@llm.service.

Usage :
    python tools/benchmark_llm_v4.py
    python tools/benchmark_llm_v4.py --reps 3
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
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
    get_model_details,
)

NERON_ROOT = Path(__file__).resolve().parents[1]
NERON_YAML_PATH = NERON_ROOT / "neron.yaml"
TEST_SERVICE = Path(__file__).resolve().parent / "llm_v3_test_service.py"  # reutilise V3 tel quel
TMP_CONFIG_DIR = Path(tempfile.gettempdir()) / "neron_bench_v4_configs"

MODEL = "qwen2.5:1.5b"
NUM_PREDICTS = [64, 80, 96, 128, 160]
BASE_PORT = 8766  # 8766..8770, un par valeur
TEST_HOST = "127.0.0.1"
TOKENS_PER_WORD_RATIO = 1.85  # mesure empirique V2 (francais, qwen/llama)

# ── Dataset (V3 + 2 nouveaux prompts longs, section 5-6 de la mission) ──

PROMPTS: list[dict] = [
    {"id": "A1", "cat": "A_courte", "prompt": "Quelle est la capitale de la France ?", "expected": "paris"},
    {"id": "A2", "cat": "A_courte", "prompt": "Combien font 12 x 8 ?", "expected": "96"},
    {"id": "A3", "cat": "A_courte", "prompt": "Quel jour sommes-nous ?", "expected": None},
    {"id": "A4", "cat": "A_courte", "prompt": "Quelle heure est-il ?", "expected": None},
    {"id": "B1", "cat": "B_naturelle", "prompt": "Explique-moi simplement ce qu'est Linux.", "expected": None},
    {"id": "B2", "cat": "B_naturelle", "prompt": "A quoi sert une API REST ?", "expected": None},
    {"id": "B3", "cat": "B_naturelle", "prompt": "Quelle est la difference entre une IA et un LLM ?", "expected": None},
    {"id": "C1", "cat": "C_stricte", "prompt": "Reponds uniquement par OK.", "expected": "ok"},
    {"id": "C2", "cat": "C_stricte", "prompt": "Reponds uniquement avec un nombre.\nCombien font 25 + 17 ?", "expected": "42"},
    {"id": "C3", "cat": "C_stricte", "prompt": "Donne-moi trois mots pour decrire Linux.", "expected": None},
    {"id": "D1", "cat": "D_raisonnement", "prompt": "J'ai 10 pommes. J'en donne 3 puis j'en achete 5. Combien m'en reste-t-il ?", "expected": "12"},
    {"id": "D2", "cat": "D_raisonnement", "prompt": "Je pars a 8h30 et mon trajet dure 1h45. A quelle heure arrive-je ?", "expected": "10h15"},
    {"id": "D3", "cat": "D_raisonnement", "prompt": "Un film commence a 20h30 et dure 2h15. A quelle heure se termine-t-il ?", "expected": "22h45"},
    {"id": "E1", "cat": "E_contexte", "prompt": (
        "Tu es Neron, un assistant personnel local.\n"
        "Tu dois repondre de maniere concise, precise et naturelle.\n"
        "Quel est ton role ?"
    ), "expected": None},
    {"id": "E2", "cat": "E_contexte", "prompt": (
        "Tu es Neron.\n"
        "L'utilisateur te demande une information simple.\n"
        "Privilegie une reponse courte plutot qu'une longue explication.\n"
        "Explique ce qu'est Docker."
    ), "expected": None},
    {"id": "E3", "cat": "E_contexte", "prompt": (
        "Tu es un assistant personnel.\n"
        "Si une question est simple, reponds directement sans ajouter d'informations inutiles.\n"
        "Pourquoi utilise-t-on Linux sur un serveur ?"
    ), "expected": None},
    {"id": "L1", "cat": "L_longueur", "prompt": "Explique-moi les principales differences entre Linux et Windows en quelques points.", "expected": None},
    {"id": "L2", "cat": "L_longueur", "prompt": "Explique-moi simplement comment fonctionne un serveur web.", "expected": None},
    {"id": "L3", "cat": "L_longueur", "prompt": "Explique le fonctionnement general d'un LLM a quelqu'un qui ne connait pas l'intelligence artificielle.", "expected": None},
    {"id": "L4", "cat": "L_longueur", "prompt": "Explique-moi les principales etapes necessaires pour creer une application web moderne.", "expected": None},
    {"id": "L5", "cat": "L_longueur", "prompt": "Explique simplement ce qu'est une API REST et donne-moi un exemple concret de son utilisation.", "expected": None},
]


# ── Config temporaire + instances jetables (une par num_predict) ─────────

def make_temp_config(num_predict: int) -> Path:
    TMP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(NERON_YAML_PATH.read_text())
    cfg["llm"]["ollama_num_predict"] = num_predict
    fd, path_str = tempfile.mkstemp(prefix=f"neron_v4_np{num_predict}_", suffix=".yaml", dir=TMP_CONFIG_DIR)
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


def start_instance(port: int, tmp_cfg: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["NERON_CONFIG"] = str(tmp_cfg)
    env.pop("NERON_API_KEY", None)
    return subprocess.Popen(
        [sys.executable, str(TEST_SERVICE), "--host", TEST_HOST, "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def wait_ready(port: int, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"http://{TEST_HOST}:{port}/v3_ready", timeout=3.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


# ── Sante systeme / pre-vol (section 4) ───────────────────────────────

def system_health() -> dict:
    load1, load5, load15 = os.getloadavg()
    hw = get_hardware_info()
    return {"load1": load1, "load5": load5, "load15": load15, "ram_available_mb": hw["ram_available_mb"]}


def preflight_checks() -> dict:
    print("=== Pre-vol V4 ===")
    report: dict = {}

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

    out = subprocess.run(
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend"],
        capture_output=True, text=True, timeout=10,
    ).stdout
    neron_services = [l.split()[0] for l in out.splitlines() if "neron" in l.lower()]
    report["neron_services_running"] = neron_services
    print(f"Services NeronOS actifs : {len(neron_services)}")

    hw = get_hardware_info()
    load1, load5, load15 = os.getloadavg()
    report["hardware"] = hw
    report["load_avg"] = {"1min": load1, "5min": load5, "15min": load15}
    print(f"CPU : {hw['cpu']} ({hw['cpu_count']} coeurs) | RAM dispo : {hw['ram_available_mb']} MiB")
    print(f"Load avg : {load1:.2f}/{load5:.2f}/{load15:.2f}")

    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        swap_total = int(re.search(r"SwapTotal:\s+(\d+)", meminfo).group(1)) // 1024
        swap_free = int(re.search(r"SwapFree:\s+(\d+)", meminfo).group(1)) // 1024
        report["swap_mb"] = {"total": swap_total, "free": swap_free, "used": swap_total - swap_free}
        print(f"Swap : {swap_total - swap_free} / {swap_total} MiB utilises")
    except Exception as exc:
        report["swap_mb"] = f"erreur: {exc}"

    node_procs = subprocess.run(["pgrep", "-fa", "node "], capture_output=True, text=True).stdout.strip()
    node_lines = [l for l in node_procs.splitlines() if "neronOS" not in l and "/usr/bin/pnpm" not in l]
    report["external_node_processes"] = node_lines
    if node_lines:
        print(f"[ATTENTION] Process Node externes a NeronOS detectes :\n" + "\n".join(f"  {l}" for l in node_lines))
    else:
        print("Aucun process Node externe a NeronOS detecte.")

    try:
        docker_out = subprocess.run(["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
                                      capture_output=True, text=True, timeout=10).stdout.strip()
        report["docker_containers"] = docker_out.splitlines() if docker_out else []
        print(f"Conteneurs Docker actifs : {len(report['docker_containers'])}")
        for line in report["docker_containers"]:
            print(f"  {line}")
    except FileNotFoundError:
        report["docker_containers"] = []
        print("docker CLI non disponible dans ce contexte (verification ignoree).")

    who_out = subprocess.run(["who"], capture_output=True, text=True).stdout.strip()
    report["active_sessions"] = who_out.splitlines() if who_out else []
    print(f"Sessions utilisateur actives : {len(report['active_sessions'])}")
    for line in report["active_sessions"]:
        print(f"  {line}")

    top_cpu = subprocess.run(["ps", "-eo", "pid,user,pcpu,comm", "--sort=-pcpu"],
                               capture_output=True, text=True).stdout.splitlines()[1:6]
    report["top_cpu_processes"] = top_cpu
    print("Top 5 CPU :")
    for line in top_cpu:
        print(f"  {line}")

    other_bench = subprocess.run(["pgrep", "-f", "benchmark_llm"], capture_output=True, text=True).stdout.strip()
    excluded = {str(os.getpid()), str(os.getppid())}
    other_pids = [p for p in other_bench.splitlines() if p not in excluded]
    report["other_benchmarks_running"] = other_pids
    if other_pids:
        print(f"[ATTENTION] Autres process benchmark_llm* : {other_pids}")
    else:
        print("Aucun autre benchmark actif.")

    return report


# ── Appel + classification ─────────────────────────────────────────────

def call_generate(port: int, prompt: str, timeout_s: float) -> dict:
    t0 = time.monotonic()
    error = None
    result_text = None
    latency_ms_api = None
    model_used = None
    status_code = None
    try:
        r = httpx.post(
            f"http://{TEST_HOST}:{port}/llm/generate",
            json={"task_type": "chat", "prompt": prompt, "model_preference": MODEL},
            timeout=timeout_s,
        )
        status_code = r.status_code
        wall_s = time.monotonic() - t0
        if r.status_code == 200:
            data = r.json()
            result_text = data.get("result")
            latency_ms_api = data.get("latency_ms")
            model_used = data.get("model_used")
            if model_used and model_used != MODEL:
                error = f"modele reellement utilise = '{model_used}' (fallback, pas '{MODEL}')"
        else:
            error = f"HTTP {r.status_code}: {r.text[:200]}"
    except httpx.TimeoutException:
        wall_s = time.monotonic() - t0
        error = f"timeout > {timeout_s}s"
    except Exception as exc:
        wall_s = time.monotonic() - t0
        error = str(exc)

    return {
        "model": MODEL, "model_used": model_used, "http_status": status_code, "error": error,
        "response_text": result_text,
        "response_len_chars": len(result_text) if result_text else 0,
        "response_len_words": len(result_text.split()) if result_text else 0,
        "latency_ms_client": round(wall_s * 1000),
        "latency_ms_api_reported": latency_ms_api,
        "eval_count": "N/A", "ttft_ms": "N/A", "tokens_per_second": "N/A",
    }


def classify_response(text: str | None, error: str | None, num_predict: int, expected: str | None) -> list[str]:
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
    # mot coupe : dernier "mot" fini par une lettre alors que la phrase n'est pas ponctuee,
    # et n'est pas un mot francais plausible tres court (ex: "et", "un") — heuristique simple :
    # un mot coupe est souvent long (>2 caracteres) et sans ponctuation finale.
    looks_cut_word = (not ends_clean) and len(last_word) > 2 and last_word.isalpha()
    near_limit = est_tokens >= max(5, num_predict - 8)  # a moins de ~8 tokens estimes de la limite

    truncated = (not ends_clean) and (near_limit or looks_cut_word) and len(words) >= 3
    if truncated:
        tags.append("TRUNCATED")
    else:
        tags.append("COMPLETE")

    if expected is not None:
        norm = re.sub(r"[^a-z0-9]", "", text.lower())
        norm_expected = re.sub(r"[^a-z0-9]", "", expected.lower())
        if norm_expected in norm:
            tags.append("CORRECT")
        else:
            tags.append("INCORRECT")

    return tags


# ── Ordre entrelace (section 8) ────────────────────────────────────────

def build_round_orders(n_rounds: int, seed: int) -> list[list[int]]:
    """n_rounds permutations independantes des 5 valeurs de num_predict."""
    rnd = random.Random(seed)
    orders = []
    for _ in range(n_rounds):
        seq = NUM_PREDICTS[:]
        rnd.shuffle(seq)
        orders.append(seq)
    return orders


# ── Agregation ─────────────────────────────────────────────────────────

def aggregate(raw_path: Path) -> dict:
    from collections import defaultdict
    by_np: dict[int, list[dict]] = defaultdict(list)
    with open(raw_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("is_warmup"):
                continue
            by_np[r["num_predict"]].append(r)

    summary = {}
    for np_val, recs in by_np.items():
        n = len(recs)
        ok = [r for r in recs if "ERROR" not in r["tags"]]
        n_ok = len(ok)
        lat = sorted(r["latency_ms_client"] for r in ok)
        truncated = [r for r in ok if "TRUNCATED" in r["tags"]]
        empty = [r for r in recs if "EMPTY" in r["tags"]]
        errors = [r for r in recs if "ERROR" in r["tags"]]
        correct = [r for r in ok if "CORRECT" in r["tags"]]
        incorrect = [r for r in ok if "INCORRECT" in r["tags"]]
        near_limit = [r for r in ok if (r["response_len_words"] * TOKENS_PER_WORD_RATIO) >= (np_val - 8)]

        def pct(p, arr):
            if not arr:
                return None
            k = (len(arr) - 1) * p
            f_, c_ = int(k), min(int(k) + 1, len(arr) - 1)
            return arr[f_] if f_ == c_ else arr[f_] + (arr[c_] - arr[f_]) * (k - f_)

        summary[str(np_val)] = {
            "n_total": n, "n_success": n_ok,
            "success_rate_pct": round(100 * n_ok / n, 1) if n else None,
            "error_rate_pct": round(100 * len(errors) / n, 1) if n else None,
            "empty_rate_pct": round(100 * len(empty) / n, 1) if n else None,
            "truncation_rate_pct": round(100 * len(truncated) / n_ok, 1) if n_ok else None,
            "limit_hit_rate_pct_estime": round(100 * len(near_limit) / n_ok, 1) if n_ok else None,
            "correctness_pct_sur_prompts_verifiables": round(100 * len(correct) / (len(correct) + len(incorrect)), 1) if (correct or incorrect) else None,
            "latency_ms_mean": round(statistics.mean(lat), 1) if lat else None,
            "latency_ms_median": round(statistics.median(lat), 1) if lat else None,
            "latency_ms_stdev": round(statistics.stdev(lat), 1) if len(lat) > 1 else (0.0 if lat else None),
            "latency_ms_min": min(lat) if lat else None,
            "latency_ms_max": max(lat) if lat else None,
            "latency_ms_p95": round(pct(0.95, lat), 1) if lat else None,
            "response_len_words_mean": round(statistics.mean([r["response_len_words"] for r in ok]), 1) if ok else None,
            "response_len_words_median": statistics.median([r["response_len_words"] for r in ok]) if ok else None,
        }
    return summary


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=3, help="Mesures reelles par (num_predict, prompt). Defaut 3 (reduit de 5, documente section 7).")
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--load-avg-threshold", type=float, default=4.0)
    ap.add_argument("--max-pause-s", type=float, default=1800.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    md5_before = subprocess.run(["md5sum", str(NERON_YAML_PATH)], capture_output=True, text=True).stdout.strip()

    preflight = preflight_checks()
    if preflight["other_benchmarks_running"]:
        sys.exit("Un autre benchmark_llm* tourne deja — abandon (mission section 4).")
    load1 = preflight["load_avg"]["1min"]
    if load1 > args.load_avg_threshold:
        print(f"\n[ARRET PROPRE] load1={load1:.2f} > seuil {args.load_avg_threshold} avant meme de commencer — abandon.")
        sys.exit(1)
    if preflight["external_node_processes"] or preflight["docker_containers"]:
        print("\n[ATTENTION] Contention potentielle detectee (Node externe ou Docker actif) — "
              "documentee ci-dessus, poursuite car load average reste sous le seuil.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / f"raw_{ts}.jsonl"
    meta_path = RESULTS_DIR / f"meta_{ts}.json"
    summary_json_path = RESULTS_DIR / f"summary_{ts}.json"
    summary_csv_path = RESULTS_DIR / f"summary_{ts}.csv"
    report_path = RESULTS_DIR / f"report_v4_{ts}.md"

    ports = {np_val: BASE_PORT + i for i, np_val in enumerate(NUM_PREDICTS)}
    tmp_configs = {np_val: make_temp_config(np_val) for np_val in NUM_PREDICTS}
    procs: dict[int, subprocess.Popen] = {}
    total_pause = 0.0
    aborted_reason = None

    print(f"\n=== Lancement de {len(NUM_PREDICTS)} instances jetables (une par num_predict) ===")
    try:
        for np_val in NUM_PREDICTS:
            procs[np_val] = start_instance(ports[np_val], tmp_configs[np_val])
        for np_val in NUM_PREDICTS:
            ok = wait_ready(ports[np_val], 60.0)
            print(f"  num_predict={np_val} (port {ports[np_val]}) : {'pret' if ok else 'ECHEC'}")
            if not ok:
                aborted_reason = f"instance_np{np_val}_non_prete"

        if not aborted_reason:
            details = get_model_details(MODEL)
            print(f"\nModele : {MODEL} ({details['parameter_size']}, {details['quantization_level']})")

            meta = {
                "timestamp_utc": ts, "mission": "V4 recherche seuil num_predict",
                "model": MODEL, "num_predicts": NUM_PREDICTS,
                "reps": args.reps, "warmup": args.warmup, "seed": args.seed,
                "reps_reduced_from_5": args.reps < 5,
                "preflight": preflight, "md5_neron_yaml_before": md5_before,
                "test_service": "5 instances FastAPI jetables paralleles (une par num_predict), "
                                 "montant le vrai router server/llm/api/routes.py, sans create_service_app "
                                 "(pas d'enregistrement registry), chacune sur son port avec sa propre copie "
                                 "temporaire de neron.yaml.",
                "tokens_per_word_ratio_utilise": TOKENS_PER_WORD_RATIO,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str))

            n_rounds = args.warmup + args.reps
            with open(raw_path, "a") as fh:
                for pi, p in enumerate(PROMPTS):
                    round_orders = build_round_orders(n_rounds, seed=args.seed + pi)
                    print(f"\n--- {p['id']} [{p['cat']}] : {p['prompt'][:50]!r} ---")
                    run_counts = {np_val: 0 for np_val in NUM_PREDICTS}
                    for round_idx, order in enumerate(round_orders):
                        is_warmup = round_idx < args.warmup
                        for np_val in order:
                            health = system_health()
                            if health["load1"] > args.load_avg_threshold:
                                pause_start = time.monotonic()
                                print(f"    [PAUSE SANTE] load1={health['load1']:.2f} > {args.load_avg_threshold} — attente...")
                                while system_health()["load1"] > args.load_avg_threshold:
                                    time.sleep(20)
                                    total_pause += 20
                                    if total_pause > args.max_pause_s:
                                        aborted_reason = "degradation_systeme_prolongee"
                                        break
                                if aborted_reason:
                                    break
                                print(f"    [REPRISE] apres {time.monotonic() - pause_start:.0f}s")
                            if aborted_reason:
                                break

                            if not is_warmup:
                                run_counts[np_val] += 1
                            rec = call_generate(ports[np_val], p["prompt"], args.timeout)
                            rec["tags"] = classify_response(rec["response_text"], rec["error"], np_val, p["expected"])
                            rec.update({
                                "prompt_id": p["id"], "category": p["cat"], "prompt": p["prompt"],
                                "num_predict": np_val, "is_warmup": is_warmup,
                                "run_idx": None if is_warmup else run_counts[np_val],
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            fh.flush()
                            status = "WARMUP" if is_warmup else f"run{run_counts[np_val]}"
                            print(f"    [np={np_val:3}] {status:<7} {rec['latency_ms_client']:>7}ms "
                                  f"{'+'.join(rec['tags']):<20} {'ERREUR: ' + rec['error'] if rec['error'] else 'OK'}")
                        if aborted_reason:
                            break
                    if aborted_reason:
                        break

            if aborted_reason:
                print(f"\n[ARRET PROPRE] Raison : {aborted_reason}. Donnees partielles dans {raw_path}.")

    finally:
        for np_val, proc in procs.items():
            proc.terminate()
        for np_val, proc in procs.items():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        cleanup_temp_configs()
        print("\nInstances jetables arretees, configs temporaires supprimees.")

    md5_after = subprocess.run(["md5sum", str(NERON_YAML_PATH)], capture_output=True, text=True).stdout.strip()
    integrity_ok = md5_before == md5_after
    print(f"\nIntegrite neron.yaml : avant={md5_before}  apres={md5_after}  {'OK' if integrity_ok else '!!! DIFFERENCE !!!'}")

    if raw_path.exists() and raw_path.stat().st_size > 0:
        print("\n=== Agregation ===")
        summary = aggregate(raw_path)
        summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        rows = [{"num_predict": k, **v} for k, v in summary.items()]
        with open(summary_csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nRaw -> {raw_path}\nSummary JSON -> {summary_json_path}\nSummary CSV -> {summary_csv_path}\nMeta -> {meta_path}")

    print(f"\nConfirmation integrite : {'neron.yaml inchange' if integrity_ok else 'ALERTE : neron.yaml modifie !'}")


if __name__ == "__main__":
    main()
