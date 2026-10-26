import json
from types import SimpleNamespace

from app import ask


def _mock_client(monkeypatch, response):
    class FakeClient:
        def __init__(self, **kwargs):
            self.models = SimpleNamespace(generate_content=lambda **kwargs: response)

    monkeypatch.setattr(ask.genai, "Client", FakeClient)
    monkeypatch.setattr(ask, "get_api_key", lambda: "test-key-not-for-output")


def test_ask_preserves_missing_usage_values(monkeypatch):
    _mock_client(monkeypatch, SimpleNamespace(text="回答"))
    monkeypatch.setattr(ask.time, "perf_counter", iter([5.0, 6.25]).__next__)

    result = ask.ask("質問")

    assert result.elapsed_seconds == 1.25
    assert result.answer == "回答"
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.thinking_tokens is None
    assert result.total_tokens is None


def test_json_output_contains_only_result(monkeypatch, capsys):
    usage = SimpleNamespace(
        prompt_token_count=11,
        candidates_token_count=7,
        thoughts_token_count=3,
        total_token_count=21,
    )
    _mock_client(monkeypatch, SimpleNamespace(text="回答文", usage_metadata=usage))
    monkeypatch.setattr(ask.time, "perf_counter", iter([5.0, 6.25]).__next__)
    monkeypatch.setattr("sys.argv", ["app.ask", "質問", "--json"])

    ask.main()

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result == {
        "model": ask.MODEL,
        "question": "質問",
        "elapsed_seconds": 1.25,
        "input_tokens": 11,
        "output_tokens": 7,
        "thinking_tokens": 3,
        "total_tokens": 21,
        "answer": "回答文",
    }
    assert captured.err == ""
    assert "test-key-not-for-output" not in captured.out


def test_normal_output_marks_missing_tokens_as_unavailable(monkeypatch, capsys):
    _mock_client(monkeypatch, SimpleNamespace(text="回答文"))
    monkeypatch.setattr(ask.time, "perf_counter", iter([5.0, 6.25]).__next__)
    monkeypatch.setattr("sys.argv", ["app.ask", "質問"])

    ask.main()

    captured = capsys.readouterr()
    assert "回答文" in captured.out
    assert "1.250 秒" in captured.out
    assert captured.out.count("取得できず") == 4
    assert "test-key-not-for-output" not in captured.out