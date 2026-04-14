from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.parse.geometry import GeometryProfile, PageLayoutSignature, build_geometry_profile


@dataclass(slots=True)
class GeometryGroundTruthRow:
    document_id: str
    page_number: int
    column_count: int
    has_header: bool
    has_footer: bool
    notes: str = ""


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def load_documents_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    required = {"document_id", "filename"}
    if not rows:
        raise ValueError(f"CSV is empty: {path}")
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    return rows


def load_layout_ground_truth_csv(path: Path) -> list[GeometryGroundTruthRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    required = {
        "document_id",
        "page_number",
        "column_count",
        "has_header",
        "has_footer",
    }
    if not rows:
        raise ValueError(f"CSV is empty: {path}")
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    parsed: list[GeometryGroundTruthRow] = []
    for row in rows:
        parsed.append(
            GeometryGroundTruthRow(
                document_id=str(row["document_id"]).strip(),
                page_number=int(row["page_number"]),
                column_count=int(row["column_count"]),
                has_header=_parse_bool(row["has_header"]),
                has_footer=_parse_bool(row["has_footer"]),
                notes=str(row.get("notes", "")).strip(),
            )
        )
    return parsed


def _signature_by_page_number(profile: GeometryProfile) -> dict[int, PageLayoutSignature]:
    return {sig.page_number: sig for sig in profile.page_layout_signatures}


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _binary_metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_geometry_against_ground_truth(
    pdf_root: Path,
    documents_csv: Path,
    layout_ground_truth_csv: Path,
    output_dir: Path,
) -> dict[str, Any]:
    documents = load_documents_csv(documents_csv)
    ground_truth_rows = load_layout_ground_truth_csv(layout_ground_truth_csv)

    filename_by_doc_id = {
        str(row["document_id"]).strip(): str(row["filename"]).strip()
        for row in documents
    }

    grouped_gt: dict[str, list[GeometryGroundTruthRow]] = {}
    for row in ground_truth_rows:
        grouped_gt.setdefault(row.document_id, []).append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.csv"
    errors_path = output_dir / "errors.csv"
    metrics_path = output_dir / "metrics.json"

    prediction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    total_pages = 0
    correct_columns = 0

    header_tp = header_fp = header_fn = 0
    footer_tp = footer_fp = footer_fn = 0

    evaluated_documents = 0
    missing_documents: list[str] = []

    for document_id, rows in sorted(grouped_gt.items()):
        filename = filename_by_doc_id.get(document_id)
        if not filename:
            missing_documents.append(document_id)
            continue

        pdf_path = (pdf_root / filename).resolve()
        if not pdf_path.exists():
            missing_documents.append(document_id)
            error_rows.append(
                {
                    "document_id": document_id,
                    "page_number": "",
                    "error_type": "missing_pdf",
                    "message": str(pdf_path),
                }
            )
            continue

        profile = build_geometry_profile(pdf_path)
        signatures = _signature_by_page_number(profile)
        evaluated_documents += 1

        for gt in sorted(rows, key=lambda r: r.page_number):
            pred = signatures.get(gt.page_number)
            if pred is None:
                error_rows.append(
                    {
                        "document_id": document_id,
                        "page_number": gt.page_number,
                        "error_type": "missing_page_signature",
                        "message": f"No signature for page {gt.page_number}",
                    }
                )
                continue

            total_pages += 1

            pred_columns = int(pred.page_column_count)
            pred_header = bool(pred.has_header)
            pred_footer = bool(pred.has_footer)

            correct_columns += int(pred_columns == gt.column_count)

            if pred_header and gt.has_header:
                header_tp += 1
            elif pred_header and not gt.has_header:
                header_fp += 1
            elif (not pred_header) and gt.has_header:
                header_fn += 1

            if pred_footer and gt.has_footer:
                footer_tp += 1
            elif pred_footer and not gt.has_footer:
                footer_fp += 1
            elif (not pred_footer) and gt.has_footer:
                footer_fn += 1

            prediction_rows.append(
                {
                    "document_id": document_id,
                    "filename": filename,
                    "page_number": gt.page_number,
                    "notes": gt.notes,
                    "true_column_count": gt.column_count,
                    "pred_column_count": pred_columns,
                    "column_correct": int(pred_columns == gt.column_count),
                    "true_has_header": int(gt.has_header),
                    "pred_has_header": int(pred_header),
                    "header_correct": int(pred_header == gt.has_header),
                    "true_has_footer": int(gt.has_footer),
                    "pred_has_footer": int(pred_footer),
                    "footer_correct": int(pred_footer == gt.has_footer),
                    "layout_key": pred.layout_key(),
                    "active_lane_ranges": _safe_json(pred.active_lane_ranges),
                }
            )

            if pred_columns != gt.column_count or pred_header != gt.has_header or pred_footer != gt.has_footer:
                error_rows.append(
                    {
                        "document_id": document_id,
                        "page_number": gt.page_number,
                        "error_type": "prediction_mismatch",
                        "message": _safe_json(
                            {
                                "true": {
                                    "column_count": gt.column_count,
                                    "has_header": gt.has_header,
                                    "has_footer": gt.has_footer,
                                },
                                "pred": {
                                    "column_count": pred_columns,
                                    "has_header": pred_header,
                                    "has_footer": pred_footer,
                                },
                            }
                        ),
                    }
                )

    with predictions_path.open("w", encoding="utf-8", newline="") as handle:
        if prediction_rows:
            writer = csv.DictWriter(handle, fieldnames=list(prediction_rows[0].keys()))
            writer.writeheader()
            writer.writerows(prediction_rows)
        else:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "document_id",
                    "filename",
                    "page_number",
                    "notes",
                    "true_column_count",
                    "pred_column_count",
                    "column_correct",
                    "true_has_header",
                    "pred_has_header",
                    "header_correct",
                    "true_has_footer",
                    "pred_has_footer",
                    "footer_correct",
                    "layout_key",
                    "active_lane_ranges",
                ]
            )

    with errors_path.open("w", encoding="utf-8", newline="") as handle:
        if error_rows:
            writer = csv.DictWriter(handle, fieldnames=list(error_rows[0].keys()))
            writer.writeheader()
            writer.writerows(error_rows)
        else:
            writer = csv.writer(handle)
            writer.writerow(["document_id", "page_number", "error_type", "message"])

    metrics = {
        "documents_total_in_ground_truth": len(grouped_gt),
        "documents_evaluated": evaluated_documents,
        "documents_missing": missing_documents,
        "pages_evaluated": total_pages,
        "column_accuracy": (correct_columns / total_pages) if total_pages else 0.0,
        "header_metrics": _binary_metrics(header_tp, header_fp, header_fn),
        "footer_metrics": _binary_metrics(footer_tp, footer_fp, footer_fn),
        "artifacts": {
            "predictions_csv": str(predictions_path),
            "errors_csv": str(errors_path),
            "metrics_json": str(metrics_path),
        },
    }

    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return metrics
