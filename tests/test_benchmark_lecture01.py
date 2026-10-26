import json
import sys
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

from scripts import benchmark_lecture01 as benchmark


def test_build_trials_has_twelve_trials_and_alternates_first_model():
    trials = benchmark.build_trials()

    assert len(trials) == 12
    for repetition in range(1, benchmark.REPETITIONS + 1):
        expected_order = benchmark.MODELS if repetition % 2 else tuple(reversed(benchmark.MODELS))
        for question in benchmark.QUESTIONS:
            actual_order = [
                trial.model
                for trial in trials
                if trial.repetition == repetition and trial.question == question
            ]
            assert actual_order == list(expected_order)


def test_execute_trial_uses_current_python_and_redacts_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret")
    monkeypatch.setattr(
        benchmark,
        "utc_now",
        lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )
    monkeypatch.setattr(benchmark.time, "perf_counter", iter([10.0, 13.5]).__next__)
    payload = {
        "model": benchmark.MODELS[0],
        "question": benchmark.QUESTIONS[0],
        "elapsed_seconds": 2.5,
        "input_tokens": 10,
        "output_tokens": 20,
        "thinking_tokens": None,
        "total_tokens": 30,
        "answer": "contains test-secret",
    }

    def fake_run(command, **kwargs):
        assert command[:3] == [sys.executable, "-m", "app.ask"]
        assert "--json" in command
        assert kwargs["env"]["AIE_MODEL"] == benchmark.MODELS[0]
        assert kwargs["env"]["GEMINI_API_KEY"] == "test-secret"
        assert kwargs["timeout"] == benchmark.TIMEOUT_SECONDS
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)
    trial = benchmark.build_trials()[0]
    record = benchmark.execute_trial(trial)

    assert record["status"] == "success"
    assert record["process_elapsed_seconds"] == 3.5
    assert record["api_elapsed_seconds"] == 2.5
    assert record["thinking_tokens"] is None
    assert record["answer"] == "contains [REDACTED]"
    assert "test-secret" not in json.dumps(record)


def test_timeout_keeps_api_metrics_unavailable(monkeypatch):
    monkeypatch.setattr(benchmark, "utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))
    monkeypatch.setattr(benchmark.time, "perf_counter", iter([10.0, 130.0]).__next__)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], benchmark.TIMEOUT_SECONDS)

    monkeypatch.setattr(benchmark.subprocess, "run", timeout)
    record = benchmark.execute_trial(benchmark.build_trials()[0])

    assert record["status"] == "failed"
    assert record["failure_type"] == "timeout"
    assert record["process_elapsed_seconds"] == 120.0
    assert record["api_elapsed_seconds"] is None
    assert all(record[field] is None for field in benchmark.TOKEN_FIELDS)
    assert record["answer"] is None


def test_api_error_and_invalid_json_are_saved_as_failures(monkeypatch):
    trial = benchmark.build_trials()[0]
    monkeypatch.setattr(benchmark, "utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))
    clock = iter([10.0, 10.5, 20.0, 21.0])
    monkeypatch.setattr(benchmark.time, "perf_counter", clock.__next__)
    results = iter(
        [
            SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="レート制限に達しました。詳細: test-secret",
            ),
            SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
        ]
    )
    monkeypatch.setattr(benchmark.subprocess, "run", lambda *args, **kwargs: next(results))

    api_error = benchmark.execute_trial(trial)
    invalid_json = benchmark.execute_trial(trial)

    assert api_error["failure_type"] == "api_error"
    assert invalid_json["failure_type"] == "json_parse_error"
    for record in (api_error, invalid_json):
        assert record["api_elapsed_seconds"] is None
        assert all(record[field] is None for field in benchmark.TOKEN_FIELDS)
        assert record["answer"] is None


def test_summary_ignores_null_metrics_and_handles_all_failures():
    model = benchmark.MODELS[0]
    question = benchmark.QUESTIONS[0]
    records = [
        {
            "model": model,
            "question": question,
            "status": "success",
            "api_elapsed_seconds": 2.0,
            "input_tokens": 10,
            "output_tokens": None,
            "thinking_tokens": None,
            "total_tokens": 10,
        },
        {
            "model": model,
            "question": question,
            "status": "success",
            "api_elapsed_seconds": None,
            "input_tokens": None,
            "output_tokens": None,
            "thinking_tokens": None,
            "total_tokens": None,
        },
        {"model": model, "question": question, "status": "failed"},
    ]
    records.extend(
        {
            "model": benchmark.MODELS[1],
            "question": benchmark.QUESTIONS[0],
            "status": "failed",
        }
        for _ in range(benchmark.REPETITIONS)
    )

    summary = benchmark.render_summary(records)

    assert "| 3 | 2 | 1 | 2.000 | 2.000 | 2.000 | 2.000 | 10.00 / 1 |" in summary
    assert "| 3 | 0 | 3 | 取得できず |" in summary