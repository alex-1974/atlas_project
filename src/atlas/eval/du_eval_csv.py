from __future__ import annotations

from pathlib import Path

import pandas as pd


def run_du_eval_csv(csv_path: str, repo) -> None:
    csv_file = _resolve_csv_path(csv_path)
    df = pd.read_csv(csv_file)

    required_cols = {"path", "true_document_type"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV missing required columns: {sorted(missing)}. "
            f"Found columns: {list(df.columns)}"
        )

    documents = repo.fetch_documents()
    docs_by_filename = _build_docs_by_filename(documents)

    top1_correct = 0
    top2_correct = 0
    total = 0

    print("\n=== DU EVAL (CSV) ===\n")

    for _, row in df.iterrows():
        path = str(row["path"]).strip()
        filename = Path(path).name
        true_type = str(row["true_document_type"]).strip()

        doc = docs_by_filename.get(filename)
        if not doc:
            print(f"SKIP  | not in DB: {filename}")
            continue

        doc_id = doc["document_id"]
        scores = repo.fetch_document_type_scores(doc_id)

        if not scores:
            print(f"MISS  | {true_type:<20} -> other                | {filename}")
            continue

        top1 = scores[0]["doc_type"]
        top2 = {s["doc_type"] for s in scores[:2]}

        if top1 == true_type:
            print(f"OK    | {true_type:<20} -> {top1:<20} | {filename}")
            top1_correct += 1
        else:
            print(f"MISS  | {true_type:<20} -> {top1:<20} | {filename}")

        if true_type in top2:
            top2_correct += 1

        if len(scores) >= 2:
            margin = float(scores[0]["weight"]) - float(scores[1]["weight"])
            if margin < 0.15:
                print(
                    f"  CLOSE | top1={scores[0]['doc_type']:<20} "
                    f"top2={scores[1]['doc_type']:<20} "
                    f"Δ={margin:.2f}"
                )

        total += 1

    print("\n=== SUMMARY ===\n")

    if total == 0:
        print("No evaluable documents found.")
        return

    print(f"Top-1 Accuracy: {top1_correct}/{total} = {top1_correct/total:.2f}")
    print(f"Top-2 Accuracy: {top2_correct}/{total} = {top2_correct/total:.2f}")


def _build_docs_by_filename(documents: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}

    for doc in documents:
        file_name = doc.get("file_name")
        if not file_name:
            continue

        # first match wins; filenames should usually be unique enough here
        result.setdefault(str(file_name), doc)

    return result


def _resolve_csv_path(csv_path: str) -> Path:
    p = Path(csv_path)

    if p.exists():
        return p

    candidates = [
        Path.cwd() / csv_path,
        Path(__file__).resolve().parent / csv_path,
        Path(__file__).resolve().parent / "literature ground truth.csv",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"CSV not found: {csv_path}. "
        f"Tried: {', '.join(str(c) for c in candidates)}"
    )
