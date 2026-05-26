"""
excel_tool.py — Lire et analyser des fichiers Excel (.xlsx) et CSV
Fonctionnalités : résumé, détection d'anomalies, statistiques, graphiques, export PDF
"""

import os
import io
import asyncio
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")


class ExcelTool:
    """Outil d'analyse de fichiers Excel et CSV."""

    # ─────────────────────────────────────────────
    # Chargement du fichier
    # ─────────────────────────────────────────────

    async def load_file(self, filepath: str) -> dict:
        """
        Charger un fichier Excel ou CSV.
        Retourne {success, dataframe, info, error}
        """
        return await asyncio.to_thread(self._load_file_sync, filepath)

    def _load_file_sync(self, filepath: str) -> dict:
        try:
            import pandas as pd

            path = Path(filepath)
            if not path.exists():
                return {"success": False, "error": f"Fichier introuvable : {filepath}"}

            ext = path.suffix.lower()

            if ext == ".csv":
                # Détecter le séparateur automatiquement
                df = pd.read_csv(filepath, sep=None, engine="python", encoding_errors="replace")
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(filepath)
            else:
                return {"success": False, "error": f"Format non supporté : {ext}"}

            return {
                "success": True,
                "dataframe": df,
                "info": {
                    "rows": len(df),
                    "columns": list(df.columns),
                    "dtypes": df.dtypes.astype(str).to_dict(),
                    "filename": path.name,
                }
            }

        except Exception as e:
            return {"success": False, "error": f"Erreur chargement : {e}"}

    # ─────────────────────────────────────────────
    # Résumé
    # ─────────────────────────────────────────────

    async def summarize(self, filepath: str) -> str:
        """Générer un résumé textuel du fichier."""
        result = await self.load_file(filepath)
        if not result["success"]:
            return f"❌ {result['error']}"

        return await asyncio.to_thread(self._summarize_sync, result["dataframe"], result["info"])

    def _summarize_sync(self, df, info: dict) -> str:
        import pandas as pd

        lines = [
            f"📊 **{info['filename']}** — {info['rows']} lignes × {len(info['columns'])} colonnes\n",
            f"**Colonnes :** {', '.join(f'`{c}`' for c in info['columns'])}\n"
        ]

        # Statistiques numériques
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            lines.append("**Statistiques numériques :**")
            stats = df[num_cols].describe().round(2)
            for col in num_cols[:6]:  # Limiter à 6 colonnes
                s = stats[col]
                lines.append(
                    f"- `{col}` : min={s['min']}, max={s['max']}, "
                    f"moy={s['mean']:.2f}, écart-type={s['std']:.2f}"
                )

        # Valeurs manquantes
        missing = df.isnull().sum()
        missing = missing[missing > 0]
        if not missing.empty:
            lines.append("\n**Valeurs manquantes :**")
            for col, count in missing.items():
                pct = count / len(df) * 100
                lines.append(f"- `{col}` : {count} ({pct:.1f}%)")

        # Aperçu des premières lignes
        lines.append("\n**Aperçu (5 premières lignes) :**")
        lines.append("```")
        lines.append(df.head(5).to_string(index=False))
        lines.append("```")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Détection d'anomalies
    # ─────────────────────────────────────────────

    async def detect_anomalies(self, filepath: str) -> str:
        """Détecter les anomalies dans le fichier."""
        result = await self.load_file(filepath)
        if not result["success"]:
            return f"❌ {result['error']}"

        return await asyncio.to_thread(self._detect_anomalies_sync, result["dataframe"])

    def _detect_anomalies_sync(self, df) -> str:
        import numpy as np
        import pandas as pd

        anomalies = []

        # 1. Valeurs manquantes
        missing = df.isnull().sum()
        missing = missing[missing > 0]
        if not missing.empty:
            for col, count in missing.items():
                anomalies.append(f"⚠️ **Valeurs manquantes** : `{col}` — {count} cellule(s) vide(s)")

        # 2. Doublons
        dupes = df.duplicated().sum()
        if dupes > 0:
            anomalies.append(f"⚠️ **Doublons** : {dupes} ligne(s) identique(s) détectée(s)")

        # 3. Outliers (méthode IQR) sur colonnes numériques
        num_cols = df.select_dtypes(include="number").columns
        for col in num_cols:
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outliers = df[(df[col] < lower) | (df[col] > upper)]
            if not outliers.empty:
                anomalies.append(
                    f"⚠️ **Outliers** : `{col}` — {len(outliers)} valeur(s) hors [Q1-1.5×IQR, Q3+1.5×IQR]  "
                    f"(plage normale : {lower:.2f} – {upper:.2f})"
                )

        # 4. Colonnes texte avec valeurs suspectes
        str_cols = df.select_dtypes(include="object").columns
        for col in str_cols:
            # Valeurs vides ou espaces
            empty = df[col].astype(str).str.strip().eq("").sum()
            if empty > 0:
                anomalies.append(f"⚠️ **Valeurs vides** : `{col}` — {empty} cellule(s) avec chaîne vide")

        # 5. Colonnes dates avec formats incohérents
        for col in df.columns:
            if "date" in col.lower() or "time" in col.lower():
                try:
                    parsed = pd.to_datetime(df[col], errors="coerce")
                    failed = parsed.isna().sum() - df[col].isna().sum()
                    if failed > 0:
                        anomalies.append(
                            f"⚠️ **Dates invalides** : `{col}` — {failed} valeur(s) non parsables"
                        )
                except Exception:
                    pass

        if not anomalies:
            return "✅ **Aucune anomalie détectée.** Les données semblent propres."

        result = [f"🔍 **{len(anomalies)} anomalie(s) détectée(s) :**\n"]
        result.extend(anomalies)
        return "\n".join(result)

    # ─────────────────────────────────────────────
    # Générer un graphique
    # ─────────────────────────────────────────────

    async def generate_chart(
        self,
        filepath: str,
        chart_type: str = "auto",
        x_col: str = None,
        y_col: str = None,
        title: str = None
    ) -> str:
        """
        Générer un graphique et le sauvegarder.
        Retourne le chemin vers l'image PNG.
        """
        result = await self.load_file(filepath)
        if not result["success"]:
            return None

        return await asyncio.to_thread(
            self._generate_chart_sync, result["dataframe"], result["info"],
            chart_type, x_col, y_col, title
        )

    def _generate_chart_sync(self, df, info: dict, chart_type: str, x_col, y_col, title) -> str:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.use("Agg")  # Mode non-interactif

        os.makedirs(REPORTS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(REPORTS_DIR, f"chart_{timestamp}.png")

        num_cols = df.select_dtypes(include="number").columns.tolist()
        str_cols = df.select_dtypes(include="object").columns.tolist()

        # Sélection automatique des colonnes
        if not x_col:
            x_col = str_cols[0] if str_cols else df.columns[0]
        if not y_col and num_cols:
            y_col = num_cols[0]

        chart_title = title or f"Analyse — {info['filename']}"

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(chart_title, fontsize=14, fontweight="bold")

        # Graphique 1 : distribution ou barres
        ax1 = axes[0]
        if y_col and x_col and x_col in df.columns and y_col in df.columns:
            if df[x_col].nunique() <= 20:
                group = df.groupby(x_col)[y_col].sum().sort_values(ascending=False)
                group.plot(kind="bar", ax=ax1, color="steelblue", edgecolor="white")
                ax1.set_title(f"{y_col} par {x_col}")
                ax1.tick_params(axis="x", rotation=45)
            else:
                df[y_col].dropna().plot(kind="hist", bins=20, ax=ax1, color="steelblue")
                ax1.set_title(f"Distribution — {y_col}")
        elif num_cols:
            df[num_cols[0]].dropna().plot(kind="hist", bins=20, ax=ax1, color="steelblue")
            ax1.set_title(f"Distribution — {num_cols[0]}")

        # Graphique 2 : corrélation ou camembert
        ax2 = axes[1]
        if len(num_cols) >= 2:
            df[num_cols[:5]].corr().pipe(
                lambda c: ax2.imshow(c, cmap="coolwarm", vmin=-1, vmax=1)
            )
            ax2.set_xticks(range(len(num_cols[:5])))
            ax2.set_yticks(range(len(num_cols[:5])))
            ax2.set_xticklabels(num_cols[:5], rotation=45, ha="right")
            ax2.set_yticklabels(num_cols[:5])
            ax2.set_title("Matrice de corrélation")
        elif str_cols and y_col:
            pie_data = df[x_col].value_counts().head(8)
            ax2.pie(pie_data.values, labels=pie_data.index, autopct="%1.1f%%")
            ax2.set_title(f"Répartition — {x_col}")

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        return output_path

    # ─────────────────────────────────────────────
    # Export PDF
    # ─────────────────────────────────────────────

    async def export_pdf(self, filepath: str, include_chart: bool = True) -> str:
        """Générer un rapport PDF complet."""
        summary = await self.summarize(filepath)
        anomalies = await self.detect_anomalies(filepath)

        chart_path = None
        if include_chart:
            chart_path = await self.generate_chart(filepath)

        return await asyncio.to_thread(
            self._export_pdf_sync, filepath, summary, anomalies, chart_path
        )

    def _export_pdf_sync(self, filepath: str, summary: str, anomalies: str, chart_path: str) -> str:
        from fpdf import FPDF

        os.makedirs(REPORTS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(REPORTS_DIR, f"rapport_{timestamp}.pdf")

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Rapport d'analyse — {Path(filepath).name}", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
        pdf.ln(5)

        # Résumé
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Résumé des données", ln=True)
        pdf.set_font("Helvetica", "", 9)

        # Nettoyer le markdown
        clean_summary = summary.replace("**", "").replace("`", "").replace("#", "")
        for line in clean_summary.split("\n")[:40]:
            try:
                pdf.multi_cell(0, 5, line)
            except Exception:
                pass

        pdf.ln(3)

        # Anomalies
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Anomalies détectées", ln=True)
        pdf.set_font("Helvetica", "", 9)
        clean_anomalies = anomalies.replace("**", "").replace("`", "").replace("⚠️", "[!]").replace("✅", "[OK]")
        for line in clean_anomalies.split("\n")[:20]:
            try:
                pdf.multi_cell(0, 5, line)
            except Exception:
                pass

        # Graphique
        if chart_path and Path(chart_path).exists():
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "Visualisations", ln=True)
            pdf.image(chart_path, x=10, w=190)

        pdf.output(output_path)
        return output_path
