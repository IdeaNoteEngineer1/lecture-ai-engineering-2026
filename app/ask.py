"""第1回: 素のLLMに1回だけ質問するスクリプト。

使い方:
    uv run python -m app.ask "LoRAとは何ですか？"
    uv run python -m app.ask            # 質問を省略すると、講座に固有の質問をする

ツールも会話履歴も持たない「素の」呼び出し。
講座に固有のことを聞くと、「分からない」と答えるか、一般論でもっともらしく答える
（講座の実際とは違う）ことを確かめよう。
（第3回で、用語集を検索できるエージェントにして改善する）
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass

from google import genai
from google.genai import errors

from app.config import MODEL, api_error_message, get_api_key

# 講座に固有の質問。正しい答えは data/glossary.json の homework-levels にある
DEFAULT_QUESTION = "AIE2026の講座の宿題にある「3レベル」とは何ですか？"


@dataclass
class AskResult:
    model: str
    question: str
    elapsed_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    total_tokens: int | None
    answer: str


def ask(question: str) -> AskResult:
    client = genai.Client(api_key=get_api_key())
    started_at = time.perf_counter()
    response = client.models.generate_content(model=MODEL, contents=question)
    elapsed_seconds = time.perf_counter() - started_at

    usage = getattr(response, "usage_metadata", None)

    return AskResult(
        model=MODEL,
        question=question,
        elapsed_seconds=elapsed_seconds,
        input_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        thinking_tokens=getattr(usage, "thoughts_token_count", None),
        total_tokens=getattr(usage, "total_token_count", None),
        answer=response.text,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="素のLLMに質問する")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--json", action="store_true", help="結果をJSONで出力する")
    args = parser.parse_args()

    try:
        result = ask(args.question)
    except errors.APIError as e:
        print(api_error_message(e.code, e.message), file=sys.stderr if args.json else sys.stdout)
        raise SystemExit(1)

    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False))
        return

    def display(value: int | None) -> str:
        return str(value) if value is not None else "取得できず"

    print(f"[model] {result.model}")
    print(f"[質問] {result.question}\n")
    print(result.answer)
    print(f"\n[経過時間] {result.elapsed_seconds:.3f} 秒")
    print(f"[入力トークン数] {display(result.input_tokens)}")
    print(f"[出力トークン数] {display(result.output_tokens)}")
    print(f"[思考トークン数] {display(result.thinking_tokens)}")
    print(f"[合計トークン数] {display(result.total_tokens)}")


if __name__ == "__main__":
    main()
