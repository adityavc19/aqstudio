"""Compare Sarvam-hosted models on the real pipeline: `uv run python scripts/eval_models.py`.

Needs SARVAM_API_KEY in the environment or .env. Runs each model several times on one synthetic
messy dataset and reports speed and how many claims the verifier rejects, with the reasons.
"""

import re
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping
from aqstudio.llm.client import LLMError
from aqstudio.llm.sarvam_client import SarvamClient
from aqstudio.pipeline import build_brief
from aqstudio.schemas import Brief, Persona

MODELS = ["gemma4", "glm5.3-flash", "sarvam-105b", "deepseekv4.1-flash-1017"]
RUNS = 3


def dataset() -> str:
    """Three stations: one clean, one with a sensor-fault run and a gap, one polluted."""
    rows = ["Station ID,Station Name,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3),SO2 (ug/m3)"]
    for h in range(24):
        rows.append(f"S1,Peenya,2024-01-01T{h:02d}:00:00Z,{40 + h},{90 + h},{25 + h},{10 + h // 3}")
        v = "500" if 4 <= h < 14 else 30 + h
        pm10 = "" if h >= 18 else 70 + h
        rows.append(f"S2,Jayanagar,2024-01-01T{h:02d}:00:00Z,{v},{pm10},{20 + h},8")
        rows.append(f"S3,Hebbal,2024-01-01T{h:02d}:00:00Z,{110 + h},{200 + h},{60 + h},15")
    return "\n".join(rows)


class Recorder:
    """Wraps a client so the facts it was given can be re-verified afterwards."""

    def __init__(self, inner: SarvamClient) -> None:
        self.inner, self.facts, self.drafts = inner, [], []

    def interpret_facts(self, facts, persona, context):  # type: ignore[no-untyped-def]
        self.facts = facts
        self.drafts = self.inner.interpret_facts(facts, persona, context)
        return self.drafts


def run(model: str, key: str) -> tuple[str, float, Brief | None, str]:
    """Build one brief with the given model."""
    table = parse_long_csv(dataset())
    mapping, assumptions = propose_mapping(table)
    start = time.time()
    try:
        brief, _ = build_brief(
            table,
            mapping,
            assumptions,
            False,
            None,
            frozenset(),
            Persona.WARD_OFFICER,
            None,
            None,
            SarvamClient(key, model),
        )
    except LLMError as exc:
        return model, time.time() - start, None, str(exc)
    return model, time.time() - start, brief, ""


def main() -> None:
    """Run the comparison and print a table."""
    key = re.search(r"^SARVAM_API_KEY=(.*)$", Path(".env").read_text(), re.M)
    if key is None:
        raise SystemExit("SARVAM_API_KEY not found in .env")
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(
                lambda m: run(m, key.group(1).strip()), [m for m in MODELS for _ in range(RUNS)]
            )
        )
    print(f"{'model':26}{'ok':>5}{'sec':>7}{'claims':>8}{'rejected':>10}  rejection reasons")
    for model in MODELS:
        done = [r for r in results if r[0] == model and r[2] is not None]
        if not done:
            print(f"{model:26}{0:>5}  FAILED: {next(r[3] for r in results if r[0] == model)[:80]}")
            continue
        claims = [c for _, _, b, _ in done if b for c in b.claims]
        reasons = Counter(re.sub(r"[\d.]+", "#", n)[:48] for c in claims for n in c.notes)
        print(
            f"{model:26}{len(done):>3}/{RUNS}{statistics.mean(r[1] for r in done):>7.1f}"
            f"{len(claims) / len(done):>8.1f}{sum(bool(c.notes) for c in claims):>10}  "
            f"{dict(reasons.most_common(3))}"
        )


if __name__ == "__main__":
    main()
