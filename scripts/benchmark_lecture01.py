"""第1回のモデル比較実験を直列実行し、結果と集計を保存する。

実行:
    uv run python scripts/benchmark_lecture01.py

各試行の結果は lectures/01/results/<UTC日時>/trials.jsonl に保存される。
"""

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "lectures" / "01" / "results"
MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")
AVAILABLE_MODELS = (*MODELS, "gemini-3.1-flash-lite")
QUESTIONS = (
    "LoRAとは何ですか？",
    "AIE2026の講座の宿題にある「3レベル」とは何ですか？",
)
REPETITIONS = 3
WAIT_SECONDS = 20
TIMEOUT_SECONDS = 120
JSON_FIELDS = (
    "model",
    "question",
    "elapsed_seconds",
    "input_tokens",
    "output_tokens",
    "thinking_tokens",
    "total_tokens",
    "answer",
)
TOKEN_FIELDS = ("input_tokens", "output_tokens", "thinking_tokens", "total_tokens")


@dataclass(frozen=True)
class Trial:
    order: int
    model: str
    question: str
    repetition: int


def build_trials(models: tuple[str, ...] = MODELS) -> list[Trial]:
    trials = []
    for repetition in range(1, REPETITIONS + 1):
        model_order = models if repetition % 2 or len(models) == 1 else tuple(reversed(models))
        for question in QUESTIONS:
            for model in model_order:
                trials.append(
                    Trial(
                        order=len(trials) + 1,
                        model=model,
                        question=question,
                        repetition=repetition,
                    )
                )
    return trials


def utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_run_directory(started_at: datetime) -> Path:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    prefix = started_at.strftime("%Y%m%dT%H%M%S.%fZ")
    suffix = 0
    while True:
        name = prefix if suffix == 0 else f"{prefix}-{suffix}"
        path = RESULTS_ROOT / name
        try:
            path.mkdir()
            return path
        except FileExistsError:
            suffix += 1


def _empty_result(trial: Trial, started_at: str, process_elapsed: float) -> dict[str, Any]:
    return {
        "started_at": started_at,
        "order": trial.order,
        "model": trial.model,
        "question": trial.question,
        "repetition": trial.repetition,
        "status": "failed",
        "failure_type": None,
        "return_code": None,
        "process_elapsed_seconds": process_elapsed,
        "api_elapsed_seconds": None,
        "input_tokens": None,
        "output_tokens": None,
        "thinking_tokens": None,
        "total_tokens": None,
        "answer": None,
    }


def _optional_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _optional_tokens(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _is_api_error(stderr: str) -> bool:
    message = stderr.lstrip()
    return message.startswith(
        ("レート制限に達しました", "モデルが混み合っています", "APIキーかモデル名に問題があります", "APIエラー")
    )


def _redact_secret(answer: object, secret: str | None) -> object:
    if isinstance(answer, str) and secret:
        return answer.replace(secret, "[REDACTED]")
    return answer


def execute_trial(trial: Trial, timeout_seconds: int = TIMEOUT_SECONDS) -> dict[str, Any]:
    started_at = _timestamp(utc_now())
    child_environment = os.environ.copy()
    child_environment["AIE_MODEL"] = trial.model

    process_started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.ask", "--json", trial.question],
            cwd=PROJECT_ROOT,
            env=child_environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = _empty_result(trial, started_at, time.perf_counter() - process_started)
        result["failure_type"] = "timeout"
        return result
    except OSError:
        result = _empty_result(trial, started_at, time.perf_counter() - process_started)
        result["failure_type"] = "process_start_error"
        return result

    process_elapsed = time.perf_counter() - process_started
    if completed.returncode != 0:
        result = _empty_result(trial, started_at, process_elapsed)
        result["failure_type"] = "api_error" if _is_api_error(completed.stderr) else "child_process_error"
        result["return_code"] = completed.returncode
        return result

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = _empty_result(trial, started_at, process_elapsed)
        result["failure_type"] = "json_parse_error"
        result["return_code"] = completed.returncode
        return result

    if not isinstance(payload, dict) or any(field not in payload for field in JSON_FIELDS):
        result = _empty_result(trial, started_at, process_elapsed)
        result["failure_type"] = "invalid_json_result"
        result["return_code"] = completed.returncode
        return result

    secret = child_environment.get("GEMINI_API_KEY")
    return {
        "started_at": started_at,
        "order": trial.order,
        "model": trial.model,
        "question": trial.question,
        "repetition": trial.repetition,
        "status": "success",
        "failure_type": None,
        "return_code": completed.returncode,
        "process_elapsed_seconds": process_elapsed,
        "api_elapsed_seconds": _optional_seconds(payload["elapsed_seconds"]),
        "input_tokens": _optional_tokens(payload["input_tokens"]),
        "output_tokens": _optional_tokens(payload["output_tokens"]),
        "thinking_tokens": _optional_tokens(payload["thinking_tokens"]),
        "total_tokens": _optional_tokens(payload["total_tokens"]),
        "answer": _redact_secret(payload["answer"], secret),
    }


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
        output.flush()
        os.fsync(output.fileno())


def build_metadata(
    started_at: datetime,
    models: tuple[str, ...] = MODELS,
    timeout_seconds: int = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return {
        "started_at": _timestamp(started_at),
        "models": list(models),
        "questions": list(QUESTIONS),
        "repetitions_per_model_question": REPETITIONS,
        "planned_trials": len(build_trials(models)),
        "first_model_by_repetition": {
            str(repetition): models[0] if repetition % 2 or len(models) == 1 else models[1]
            for repetition in range(1, REPETITIONS + 1)
        },
        "delay_between_trials_seconds": WAIT_SECONDS,
        "timeout_per_trial_seconds": timeout_seconds,
        "generation_settings": "app.ask defaults; no generation settings overridden",
        "process_elapsed_seconds_definition": "Parent-side subprocess.run duration, including process startup and completion.",
        "api_elapsed_seconds_definition": "app.ask elapsed_seconds for generate_content only.",
        "python_version": platform.python_version(),
        "google_genai_version": version("google-genai"),
    }


def _numeric_values(records: list[dict[str, Any]], field: str) -> list[float]:
    values = []
    for record in records:
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if math.isfinite(value):
            values.append(float(value))
    return values


def _format_number(value: float | None, digits: int = 3) -> str:
    return "取得できず" if value is None else f"{value:.{digits}f}"


def _format_token_summary(values: list[float]) -> str:
    average = statistics.mean(values) if values else None
    return f"{_format_number(average, 2)} / {len(values)}"


def render_summary(records: list[dict[str, Any]], models: tuple[str, ...] = MODELS) -> str:
    lines = [
        "# 第1回 モデル比較実験の集計",
        "",
        "時間・トークンの統計は成功試行の取得値のみを対象とし、null は除外しています。",
        "子プロセス全体の所要時間ではなく、`app.ask` が測定した API 応答時間を集計しています。",
        "",
        "| モデル | 質問 | 予定 | 成功 | 失敗 | API時間 平均 (秒) | 中央値 (秒) | 最小 (秒) | 最大 (秒) | 入力 平均 / 件数 | 出力 平均 / 件数 | 思考 平均 / 件数 | 合計 平均 / 件数 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for model in models:
        for question in QUESTIONS:
            group = [
                record
                for record in records
                if record.get("model") == model and record.get("question") == question
            ]
            successful = [record for record in group if record.get("status") == "success"]
            failed_count = sum(record.get("status") == "failed" for record in group)
            response_times = _numeric_values(successful, "api_elapsed_seconds")
            average = statistics.mean(response_times) if response_times else None
            median = statistics.median(response_times) if response_times else None
            minimum = min(response_times) if response_times else None
            maximum = max(response_times) if response_times else None
            token_averages = [
                _format_token_summary(_numeric_values(successful, field)) for field in TOKEN_FIELDS
            ]
            escaped_question = question.replace("|", "\\|").replace("\n", " ")
            cells = [
                model,
                escaped_question,
                str(sum(trial.model == model and trial.question == question for trial in build_trials(models))),
                str(len(successful)),
                str(failed_count),
                _format_number(average),
                _format_number(median),
                _format_number(minimum),
                _format_number(maximum),
                *token_averages,
            ]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="第1回のモデル比較実験を直列実行する")
    parser.add_argument(
        "--model",
        choices=AVAILABLE_MODELS,
        help="実行するモデル（省略時は既定の2モデル）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TIMEOUT_SECONDS,
        help=f"各試行のタイムアウト秒数（既定: {TIMEOUT_SECONDS}）",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout は1以上を指定してください")

    started_at = utc_now()
    run_directory = create_run_directory(started_at)
    models = (args.model,) if args.model else MODELS
    trials = build_trials(models)
    jsonl_path = run_directory / "trials.jsonl"
    metadata = build_metadata(started_at, models, args.timeout)
    (run_directory / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"結果保存先: {run_directory.relative_to(PROJECT_ROOT)}", flush=True)
    records = []
    try:
        for index, trial in enumerate(trials):
            print(
                f"[{trial.order}/{len(trials)}] {trial.model} / "
                f"質問{QUESTIONS.index(trial.question) + 1} / 反復{trial.repetition} 開始",
                flush=True,
            )
            record = execute_trial(trial, args.timeout)
            append_jsonl(jsonl_path, record)
            records.append(record)
            print(
                f"[{trial.order}/{len(trials)}] {record['status']} "
                f"(子プロセス {record['process_elapsed_seconds']:.2f} 秒)",
                flush=True,
            )
            if index < len(trials) - 1:
                time.sleep(WAIT_SECONDS)
    finally:
        (run_directory / "summary.md").write_text(
            render_summary(records, models), encoding="utf-8"
        )

    print(f"集計保存先: {run_directory.relative_to(PROJECT_ROOT) / 'summary.md'}")


if __name__ == "__main__":
    main()