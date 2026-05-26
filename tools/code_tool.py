"""
code_tool.py — Exécution multi-langage avec détection automatique
Langages supportés : Python, JavaScript/Node, TypeScript, SQL (DuckDB), Bash, R, Ruby, PHP
Stratégie : meilleur runtime disponible par langage, retry + auto-correction via Claude
"""

import os
import sys
import shutil
import asyncio
import tempfile
import subprocess
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# Runtimes disponibles par langage
# ─────────────────────────────────────────────────────────────────

RUNTIMES = {
    "python": {
        "cmd": [sys.executable],
        "ext": ".py",
        "check": sys.executable,
        "comment": "# Python",
        "run_mode": "file",
    },
    "javascript": {
        "cmd": ["node"],
        "ext": ".js",
        "check": "node",
        "comment": "// JavaScript",
        "run_mode": "file",
    },
    "typescript": {
        "cmd": ["npx", "--yes", "ts-node", "--transpile-only"],
        "ext": ".ts",
        "check": "node",  # ts-node via npx, node doit exister
        "comment": "// TypeScript",
        "run_mode": "file",
    },
    "bash": {
        "cmd": ["bash"],
        "ext": ".sh",
        "check": "bash",
        "comment": "# Bash",
        "run_mode": "file",
    },
    "powershell": {
        "cmd": ["pwsh", "-NonInteractive", "-File"],
        "ext": ".ps1",
        "check": "pwsh",
        "comment": "# PowerShell",
        "run_mode": "file",
    },
    "r": {
        "cmd": ["Rscript"],
        "ext": ".R",
        "check": "Rscript",
        "comment": "# R",
        "run_mode": "file",
    },
    "ruby": {
        "cmd": ["ruby"],
        "ext": ".rb",
        "check": "ruby",
        "comment": "# Ruby",
        "run_mode": "file",
    },
    "php": {
        "cmd": ["php"],
        "ext": ".php",
        "check": "php",
        "comment": "<?php",
        "run_mode": "file",
    },
    "sql": {
        "cmd": None,  # Géré séparément via DuckDB
        "ext": ".sql",
        "check": None,
        "comment": "-- SQL",
        "run_mode": "duckdb",
    },
}

# Signaux de détection par langage (heuristiques)
LANGUAGE_SIGNALS = {
    "python": [
        "import ", "from ", "def ", "class ", "print(", "if __name__",
        "pandas", "numpy", "matplotlib", "plt.", "pd.", "np.",
        "asyncio", "FastAPI", "django", "flask",
    ],
    "javascript": [
        "const ", "let ", "var ", "require(", "console.log", "=>",
        "module.exports", "async function", ".then(", "fetch(",
        "document.", "window.", "process.", "npm",
    ],
    "typescript": [
        ": string", ": number", ": boolean", "interface ", "type ",
        "import type", "export type", "as unknown as", "<T>", "enum ",
    ],
    "sql": [
        "SELECT ", "FROM ", "WHERE ", "INSERT INTO", "CREATE TABLE",
        "UPDATE ", "DELETE FROM", "GROUP BY", "ORDER BY", "JOIN ",
        "ALTER TABLE", "DROP TABLE", "WITH ", "HAVING ",
    ],
    "bash": [
        "#!/bin/bash", "#!/bin/sh", "echo ", "ls ", "grep ",
        "awk ", "sed ", "chmod ", "export ", "source ",
        "${", "$(", "&&", "||", "| grep", "| awk",
    ],
    "r": [
        "library(", "data.frame(", "ggplot(", " <- ",
        "read.csv(", "summary(", "lm(", "c(", "plot(",
        "tidyverse", "dplyr", "ggplot2", "tibble",
    ],
    "powershell": [
        "Get-", "Set-", "New-", "Remove-", "Write-Host",
        "$_", "ForEach-Object", "Where-Object", "Invoke-",
        "[System.", "param(", "$PSVersionTable",
    ],
    "ruby": [
        "require '", "puts ", "def ", " do |", "end\n",
        ".each ", "Rails", "Gem", "attr_accessor",
    ],
    "php": [
        "<?php", "echo ", "$_GET", "$_POST", "->",
        "array(", "function ", "class ", "namespace ",
    ],
}


class CodeTool:
    """Exécution multi-langage avec détection auto + retry + auto-correction."""

    MAX_RETRIES = 3
    TIMEOUT = 30  # secondes

    def __init__(self):
        self._available = self._check_available_runtimes()

    # ─────────────────────────────────────────────
    # Vérifier quels runtimes sont installés
    # ─────────────────────────────────────────────

    def _check_available_runtimes(self) -> dict[str, bool]:
        """Vérifier quels runtimes sont disponibles sur le système."""
        available = {}
        for lang, cfg in RUNTIMES.items():
            check = cfg.get("check")
            if check is None:
                available[lang] = True  # SQL via DuckDB (toujours dispo)
            elif check == sys.executable:
                available[lang] = True  # Python toujours dispo
            else:
                available[lang] = shutil.which(check) is not None
        return available

    def available_languages(self) -> list[str]:
        """Retourner la liste des langages disponibles."""
        return [lang for lang, ok in self._available.items() if ok]

    # ─────────────────────────────────────────────
    # Détection automatique du langage
    # ─────────────────────────────────────────────

    def detect_language(self, code: str, hint: str = None) -> str:
        """
        Détecter le langage à partir du code ou d'un indice textuel.
        hint : ex. "javascript", "écris en R", "bash script"
        """
        # 1. Utiliser l'indice si fourni
        if hint:
            hint_lower = hint.lower()
            aliases = {
                "js": "javascript", "node": "javascript", "nodejs": "javascript",
                "ts": "typescript", "node.js": "javascript",
                "py": "python", "python3": "python",
                "sh": "bash", "shell": "bash", "zsh": "bash",
                "ps": "powershell", "ps1": "powershell",
                "rb": "ruby",
            }
            for alias, lang in aliases.items():
                if alias in hint_lower:
                    return lang
            for lang in RUNTIMES:
                if lang in hint_lower:
                    return lang

        # 2. Shebangs
        first_line = code.strip().split("\n")[0]
        if "python" in first_line:
            return "python"
        if "node" in first_line or "javascript" in first_line:
            return "javascript"
        if "/bash" in first_line or "/sh" in first_line:
            return "bash"
        if "php" in first_line:
            return "php"
        if "ruby" in first_line:
            return "ruby"
        if "Rscript" in first_line:
            return "r"

        # 3. Score par signaux
        scores: dict[str, int] = {lang: 0 for lang in LANGUAGE_SIGNALS}
        for lang, signals in LANGUAGE_SIGNALS.items():
            for signal in signals:
                if signal in code:
                    scores[lang] += 1

        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "python"

    # ─────────────────────────────────────────────
    # Exécution principale
    # ─────────────────────────────────────────────

    async def execute(
        self,
        code: str,
        language: str = None,
        description: str = "",
        hint: str = None,
    ) -> dict:
        """
        Exécuter du code dans le bon runtime.
        language : forcer le langage (optionnel)
        hint : indice textuel pour la détection automatique
        Retourne {success, stdout, stderr, language, returncode, exec_time}
        """
        lang = language or self.detect_language(code, hint)

        # SQL → DuckDB
        if lang == "sql":
            return await self._run_sql_duckdb(code, description)

        if not self._available.get(lang, False):
            # Fallback : convertir en Python si possible
            available = self.available_languages()
            fallback_msg = (
                f"Runtime `{lang}` non disponible sur ce système.\n"
                f"Langages disponibles : {', '.join(available)}"
            )
            return {"success": False, "stdout": "", "stderr": fallback_msg,
                    "language": lang, "returncode": -1, "exec_time": 0}

        return await asyncio.to_thread(self._run_file, lang, code, description)

    def _run_file(self, lang: str, code: str, description: str) -> dict:
        """Exécuter un fichier temporaire avec le bon runtime."""
        import time

        cfg = RUNTIMES[lang]
        ext = cfg["ext"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            cmd = cfg["cmd"] + [tmp_path]
            start = time.time()

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
                encoding="utf-8",
                errors="replace",
            )

            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "language": lang,
                "returncode": proc.returncode,
                "exec_time": round(time.time() - start, 2),
                "description": description,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False, "stdout": "",
                "stderr": f"Timeout {self.TIMEOUT}s dépassé.",
                "language": lang, "returncode": -1, "exec_time": self.TIMEOUT,
            }
        except FileNotFoundError:
            return {
                "success": False, "stdout": "",
                "stderr": f"Runtime `{lang}` introuvable. Installer : {cfg['cmd'][0]}",
                "language": lang, "returncode": -1, "exec_time": 0,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    async def _run_sql_duckdb(self, sql: str, description: str) -> dict:
        """Exécuter du SQL via DuckDB (in-memory, très rapide)."""
        return await asyncio.to_thread(self._run_sql_sync, sql, description)

    def _run_sql_sync(self, sql: str, description: str) -> dict:
        import time
        try:
            import duckdb
            start = time.time()
            conn = duckdb.connect(":memory:")
            result = conn.execute(sql)
            rows = result.fetchall()
            cols = [d[0] for d in result.description] if result.description else []
            conn.close()

            # Formater en tableau
            if rows:
                col_widths = [max(len(c), max(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)]
                header = " | ".join(c.ljust(w) for c, w in zip(cols, col_widths))
                sep = "-+-".join("-" * w for w in col_widths)
                lines = [header, sep]
                for row in rows[:50]:  # Limiter à 50 lignes
                    lines.append(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))
                if len(rows) > 50:
                    lines.append(f"... ({len(rows)} lignes au total)")
                output = "\n".join(lines)
            else:
                output = "(Requête exécutée, aucune ligne retournée)"

            return {
                "success": True,
                "stdout": output,
                "stderr": "",
                "language": "sql",
                "returncode": 0,
                "exec_time": round(time.time() - start, 4),
                "rows": rows,
                "columns": cols,
                "description": description,
            }
        except ImportError:
            return {"success": False, "stdout": "", "stderr": "duckdb non installé. pip install duckdb",
                    "language": "sql", "returncode": -1, "exec_time": 0}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e),
                    "language": "sql", "returncode": -1, "exec_time": 0}

    # ─────────────────────────────────────────────
    # Retry avec auto-correction via Claude
    # ─────────────────────────────────────────────

    async def execute_with_retry(
        self,
        code: str,
        description: str = "",
        language: str = None,
        hint: str = None,
        fix_callback=None,  # async (code, error, lang) -> str
    ) -> dict:
        """
        Exécuter avec correction automatique (max 3 essais).
        fix_callback : async (code: str, error: str, language: str) -> str
        """
        current_code = code
        lang = language or self.detect_language(code, hint)
        attempts = []

        for attempt in range(1, self.MAX_RETRIES + 1):
            result = await self.execute(current_code, lang, description)
            result["attempt"] = attempt
            result["code"] = current_code
            attempts.append(result)

            if result["success"]:
                return {**result, "attempts": len(attempts), "final_code": current_code, "history": attempts}

            # Erreur → tenter correction
            if fix_callback and attempt < self.MAX_RETRIES:
                error = result.get("stderr") or result.get("stdout", "Erreur inconnue")
                try:
                    current_code = await fix_callback(current_code, error, lang)
                except Exception:
                    break

        last = attempts[-1]
        return {**last, "success": False, "attempts": len(attempts),
                "final_code": current_code, "history": attempts}

    # ─────────────────────────────────────────────
    # Formattage
    # ─────────────────────────────────────────────

    @staticmethod
    def format_result(result: dict) -> str:
        lang = result.get("language", "")
        attempts = result.get("attempts", 1)
        lines = []

        if result.get("description"):
            lines.append(f"**{result['description']}**")

        lang_icons = {
            "python": "🐍", "javascript": "🟨", "typescript": "🔷",
            "sql": "🗃️", "bash": "🖥️", "r": "📊", "powershell": "💠",
            "ruby": "💎", "php": "🐘",
        }
        icon = lang_icons.get(lang, "⚙️")

        if attempts > 1:
            lines.append(f"_{icon} {lang} — corrigé en {attempts} essai(s)_")
        else:
            lines.append(f"_{icon} {lang}_")

        if result["success"]:
            lines.append("✅ **Succès**")
            if result.get("stdout"):
                lines.append(f"```\n{result['stdout']}\n```")
            if result.get("exec_time"):
                lines.append(f"_Durée : {result['exec_time']}s_")
        else:
            lines.append("❌ **Erreur**")
            err = result.get("stderr") or result.get("stdout", "")
            if err:
                lines.append(f"```\n{err[:800]}\n```")

        return "\n".join(lines)

    @staticmethod
    def code_block(code: str, language: str = "python") -> str:
        return f"```{language}\n{code}\n```"
