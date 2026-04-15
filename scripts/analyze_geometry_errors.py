#!/usr/bin/env python3
"""
Analyse der Ergebnisse der Geometry-Evaluation.

Dieses Skript wertet die erzeugten CSV-Dateien aus und erstellt:
- Fehlerübersichten
- Statistiken pro Dokument
- Klassifikation nach Dokumentlänge
"""

from pathlib import Path
import pandas as pd


PREDICTIONS_PATH = Path("evaluation/geometry_results/predictions.csv")
ERRORS_PATH = Path("evaluation/geometry_results/errors.csv")


def classify_document_length(page_count: int) -> str:
    """Klassifiziert Dokumente nach Länge."""
    if page_count < 20:
        return "short"
    elif page_count < 80:
        return "medium"
    return "long"


def main() -> None:
    if not PREDICTIONS_PATH.exists():
        print(f"Nicht gefunden: {PREDICTIONS_PATH}")
        return

    df = pd.read_csv(PREDICTIONS_PATH)

    print("\n=== Überblick ===")
    print(f"Prediction-Zeilen: {len(df)}")

    if ERRORS_PATH.exists():
        df_errors = pd.read_csv(ERRORS_PATH)
        print(f"Error-Zeilen:      {len(df_errors)}")
    else:
        df_errors = None
        print("Keine errors.csv gefunden.")

    # Fehlerarten bestimmen
    df["column_error"] = df["true_column_count"] != df["pred_column_count"]
    df["header_error"] = df["true_has_header"] != df["pred_has_header"]
    df["footer_error"] = df["true_has_footer"] != df["pred_has_footer"]

    print("\n=== Fehler nach Typ ===")
    print(f"column_errors: {df['column_error'].sum()}")
    print(f"header_errors: {df['header_error'].sum()}")
    print(f"footer_errors: {df['footer_error'].sum()}")

    # Analyse pro Dokument
    print("\n=== Analyse pro Dokument ===")
    grouped = df.groupby("filename")

    rows = []
    for filename, g in grouped:
        page_count = len(g)

        column_accuracy = (g["true_column_count"] == g["pred_column_count"]).mean()
        header_accuracy = (g["true_has_header"] == g["pred_has_header"]).mean()
        footer_accuracy = (g["true_has_footer"] == g["pred_has_footer"]).mean()

        rows.append({
            "filename": filename,
            "pages": page_count,
            "length_class": classify_document_length(page_count),
            "column_accuracy": round(column_accuracy, 3),
            "header_accuracy": round(header_accuracy, 3),
            "footer_accuracy": round(footer_accuracy, 3),
            "column_errors": int(g["column_error"].sum()),
            "header_errors": int(g["header_error"].sum()),
            "footer_errors": int(g["footer_error"].sum()),
        })

    summary_df = pd.DataFrame(rows)
    summary_df = summary_df.sort_values(by="column_accuracy")

    print(summary_df.to_string(index=False))

    # Speicherung
    output_path = Path("evaluation/geometry_results/document_summary.csv")
    summary_df.to_csv(output_path, index=False)
    print(f"\nDokumentzusammenfassung gespeichert unter:\n{output_path}")

    # Analyse nach Dokumentlänge
    print("\n=== Analyse nach Dokumentlänge ===")
    length_group = summary_df.groupby("length_class").agg({
        "column_accuracy": "mean",
        "header_accuracy": "mean",
        "footer_accuracy": "mean",
        "pages": "sum"
    }).round(3)

    print(length_group)


if __name__ == "__main__":
    main()
