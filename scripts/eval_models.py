"""LLM extraction eval runner.

Sweeps candidate models over the golden set, scores each with eval_scorer, and
writes a per-environment Markdown report (EN leaderboard + per-case failure diffs).

Reuses services.nlp_service.extract_profile_data unchanged (same prompt, JSON
parsing, retry logic) via the model/base_url seam, so scores reflect production
fidelity rather than a reimplementation.

    venv/bin/python scripts/eval_models.py \
        --env prod \
        --models mistral:7b-instruct,qwen2.5:14b,qwen2.5:32b \
        --cases scripts/eval_data/golden_set.json \
        --runs 3

The LLM endpoint defaults to the running box's own `LLM_URL` (from its .env) —
which is correct per environment: the lab laptop's points at the T4, the prod
app server's at the DGX-2 over the VLAN. Pass `--base-url` only to override it
(e.g. `http://localhost:11434/v1` when running the sweep directly on the DGX-2).
`--env` is just a label for the report file/header. The runner runs inside a
Flask app context so extract_profile_data sees config.
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

# Make imports work regardless of cwd: running `python scripts/eval_models.py`
# puts scripts/ on sys.path but NOT the repo root, so `import app`/`services`
# would fail. Add both: scripts/ (for eval_scorer) and the repo root (for the app).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
from eval_scorer import score_case  # noqa: E402


def run_eval(cases, models, extract_fn, runs=1, on_event=None):
    """Score every (model, case, run) and aggregate per model.

    extract_fn(transcripts, model) -> actual extraction dict, or raises on failure.
    A failed extraction counts toward `failures` and scores 0 for that run.
    on_event(event) -> optional progress callback, called with dicts of type
    "model_start", "case_start", and "case_done" (see main() for formatting).
    Returns {model: {accuracy_mean, latency_mean_ms, failures, runs, per_case}}.
    """
    def emit(event):
        if on_event is not None:
            on_event(event)

    results = {}
    for mi, model in enumerate(models, start=1):
        emit({"type": "model_start", "model": model,
              "model_index": mi, "model_total": len(models)})
        case_accuracies = []
        latencies_ms = []
        failures = 0
        per_case = []

        for ci, case in enumerate(cases, start=1):
            emit({"type": "case_start", "model": model, "id": case["id"],
                  "case_index": ci, "case_total": len(cases)})
            run_accuracies = []
            case_ms = 0.0
            sample_actual = None
            sample_error = None
            for _ in range(runs):
                start = time.perf_counter()
                try:
                    actual = extract_fn(case["transcripts"], model)
                    elapsed = (time.perf_counter() - start) * 1000
                    latencies_ms.append(elapsed)
                    case_ms += elapsed
                    acc = score_case(case["expected"], actual)["accuracy"]
                    run_accuracies.append(acc)
                    if sample_actual is None:
                        sample_actual = actual
                except Exception as e:  # noqa: BLE001 - any error is a scored failure
                    elapsed = (time.perf_counter() - start) * 1000
                    latencies_ms.append(elapsed)
                    case_ms += elapsed
                    failures += 1
                    run_accuracies.append(0.0)
                    sample_error = repr(e)

            case_acc = statistics.mean(run_accuracies) if run_accuracies else 0.0
            case_accuracies.append(case_acc)
            per_case.append({
                "id": case["id"],
                "accuracy": case_acc,
                "expected": case["expected"],
                "sample_actual": sample_actual,
                "error": sample_error,
            })
            emit({"type": "case_done", "model": model, "id": case["id"],
                  "case_index": ci, "case_total": len(cases),
                  "accuracy": case_acc, "failed": sample_error is not None,
                  "elapsed_ms": case_ms})

        results[model] = {
            "accuracy_mean": statistics.mean(case_accuracies) if case_accuracies else 0.0,
            "latency_mean_ms": statistics.mean(latencies_ms) if latencies_ms else 0.0,
            "failures": failures,
            "runs": runs,
            "per_case": per_case,
        }
    return results


def leaderboard(results):
    """Return [(model, stats), ...] ranked by accuracy_mean desc, then latency asc."""
    return sorted(
        results.items(),
        key=lambda kv: (-kv[1]["accuracy_mean"], kv[1]["latency_mean_ms"]),
    )


def format_report(env, results, cases):
    """Render the EN leaderboard + per-case failure diffs as Markdown."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# LLM Extraction Eval — `{env}` ({len(cases)} EN cases)",
        "",
        f"Generated {ts}",
        "",
        "## English Leaderboard",
        "",
        "| Rank | Model | Accuracy | Avg latency (ms) | Failures |",
        "|---|---|---|---|---|",
    ]
    for i, (model, s) in enumerate(leaderboard(results), start=1):
        lines.append(
            f"| {i} | `{model}` | {s['accuracy_mean']:.3f} | "
            f"{s['latency_mean_ms']:.0f} | {s['failures']} |"
        )

    lines += ["", "## Per-case failures (accuracy < 1.0)", ""]
    for model, s in leaderboard(results):
        misses = [c for c in s["per_case"] if c["accuracy"] < 1.0]
        if not misses:
            continue
        lines.append(f"### `{model}`")
        lines.append("")
        for c in misses:
            lines.append(f"- **{c['id']}** — accuracy {c['accuracy']:.3f}")
            if c["error"]:
                lines.append(f"  - extraction error: `{c['error']}`")
            lines.append(f"  - expected: `{json.dumps(c['expected'], ensure_ascii=False)}`")
            lines.append(f"  - actual:   `{json.dumps(c['sample_actual'], ensure_ascii=False)}`")
        lines.append("")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sweep candidate LLMs over the extraction golden set.")
    parser.add_argument("--env", choices=["lab", "prod"], default="prod",
                        help="Report label only (which environment you're measuring); "
                             "does not select the endpoint.")
    parser.add_argument("--base-url", default=None,
                        help="Override the LLM endpoint. Default: this box's own LLM_URL "
                             "(.env). Use e.g. http://localhost:11434/v1 when running on the DGX-2.")
    parser.add_argument("--models", required=True,
                        help="Comma-separated Ollama model tags to evaluate.")
    parser.add_argument("--cases", default="scripts/eval_data/golden_set.json",
                        help="Path to the golden set JSON.")
    parser.add_argument("--runs", type=int, default=3,
                        help="Repeat each case N times (models are stochastic) and average.")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Per-request LLM timeout (seconds). Defaults to 120 — generous "
                             "for the eval, where production's short UX timeout would kill "
                             "slower/bigger models mid-generation. Overrides config LLM_TIMEOUT.")
    parser.add_argument("--out-dir", default="scripts/eval_data",
                        help="Directory for the Markdown report.")
    args = parser.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    with open(args.cases) as f:
        cases = json.load(f)["cases"]

    # Import + app context are deferred to main() so the pure core (run_eval,
    # leaderboard, format_report) stays importable and testable without Flask.
    from flask import current_app
    from app import create_app
    from services.nlp_service import extract_profile_data

    # base_url=None -> extract_profile_data falls back to this box's config LLM_URL.
    def extract_fn(transcripts, model):
        return extract_profile_data(transcripts, model=model, base_url=args.base_url)

    def log(event):
        # Live progress to stderr, flushed so it appears during long extractions.
        if event["type"] == "model_start":
            print(f"\n[model {event['model_index']}/{event['model_total']}] "
                  f"{event['model']}", file=sys.stderr, flush=True)
        elif event["type"] == "case_start":
            print(f"  case {event['case_index']}/{event['case_total']} "
                  f"{event['id']} ...", file=sys.stderr, flush=True)
        elif event["type"] == "case_done":
            flag = "FAIL" if event["failed"] else f"acc {event['accuracy']:.3f}"
            print(f"  case {event['case_index']}/{event['case_total']} "
                  f"{event['id']} -> {flag} ({event['elapsed_ms'] / 1000:.1f}s)",
                  file=sys.stderr, flush=True)

    app = create_app()
    app.config["LLM_TIMEOUT"] = args.timeout
    with app.app_context():
        endpoint = args.base_url or current_app.config["LLM_URL"]
        print(f"Evaluating {len(models)} model(s) on {len(cases)} EN cases "
              f"({args.runs} run(s) each) against {endpoint} [label: {args.env}] "
              f"(timeout {args.timeout}s) ...",
              file=sys.stderr, flush=True)
        results = run_eval(cases, models, extract_fn, runs=args.runs, on_event=log)

    md = format_report(args.env, results, cases)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"report_{args.env}_{ts}.md")
    with open(out_path, "w") as f:
        f.write(md)

    for model, s in leaderboard(results):
        print(f"{s['accuracy_mean']:.3f}  {model}  "
              f"(latency {s['latency_mean_ms']:.0f}ms, {s['failures']} failures)")
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
