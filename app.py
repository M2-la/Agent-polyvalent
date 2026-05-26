"""
app.py — Agent IA Polyvalent avec Chainlit
Point d'entrée principal : gestion des messages, outils, streaming Claude, actions UI

Domaines :
  1. Emails       — lire Gmail / envoyer avec validation
  2. Bureautique  — analyser Excel/CSV/Parquet, graphiques (Plotly/Seaborn/Matplotlib), PDF
  3. Code         — multi-langage : Python, JS, TS, SQL, Bash, R, Ruby, PHP + retry auto
  4. Bases de données — DuckDB (analytics), SQLite, PostgreSQL, MySQL, MongoDB
  5. BI & Reporting   — dashboards HTML interactifs, PDF ReportLab, Excel, planification cron
"""

import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv

import chainlit as cl
from anthropic import AsyncAnthropic

from tools import EmailTool, ExcelTool, CodeTool, DatabaseTool, BITool

load_dotenv()

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
USER_FIRSTNAME = os.getenv("USER_FIRSTNAME", "Utilisateur")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
UPLOAD_DIR = "uploads"

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path("reports").mkdir(parents=True, exist_ok=True)
Path("data").mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# Instanciation des outils
# ─────────────────────────────────────────────

email_tool = EmailTool()
excel_tool = ExcelTool()
code_tool = CodeTool()
db_tool = DatabaseTool()
bi_tool = BITool()

# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

SYSTEM_PROMPT = f"""Tu es un expert en Business Intelligence, bases de données et développement multi-langage.
Prénom de l'utilisateur : {USER_FIRSTNAME}.

═══════════════════════════════════════
OUTILS DISPONIBLES
═══════════════════════════════════════

📧 EMAIL
  read_emails   — lire les emails non lus Gmail
  draft_email   — rédiger + afficher brouillon + attendre validation

📊 FICHIERS & DONNÉES
  analyze_file  — Excel, CSV, Parquet : résumé, anomalies, graphiques, export

🖥️ CODE MULTI-LANGAGE (subprocess isolé, retry ×3)
  execute_code  — Python • JavaScript/Node • TypeScript • SQL/DuckDB
                  Bash • R • Ruby • PHP • PowerShell
  → Détecter automatiquement le meilleur langage selon la tâche
  → Pour data science : Python + pandas/polars
  → Pour scripts système : Bash/PowerShell
  → Pour stats : R
  → Pour web/API : JavaScript/TypeScript
  → Pour requêtes analytiques : SQL via DuckDB

🗄️ BASES DE DONNÉES (multi-moteurs)
  database_query — DuckDB (analytics OLAP, SQL sur CSV/Parquet/JSON)
                   SQLite (local, léger)
                   PostgreSQL (production)
                   MySQL/MariaDB
                   MongoDB (documents NoSQL)
  → DuckDB = meilleur choix pour analytics, agrégations, jointures sur fichiers
  → SQLite = données locales simples
  → PostgreSQL = production multi-utilisateurs

📈 BI & REPORTING (production-grade)
  generate_bi_report — Dashboard HTML interactif (Plotly CDN)
                       PDF professionnel (ReportLab mise en page avancée)
                       Excel avec mise en forme (openpyxl)
                       Graphiques : bar/line/pie/scatter/area/funnel/treemap/
                                    waterfall/candlestick/gauge (Plotly)
                                    heatmap/boxplot/violin/pairplot/kde/
                                    regression (Seaborn)
                       Planification automatique (cron APScheduler)

═══════════════════════════════════════
RÈGLES STRICTES
═══════════════════════════════════════
1. Réponses courtes et concrètes — zero intro inutile
2. Avant action irréversible (envoi email, write BDD, suppression) → bouton confirmation
3. Code : essayer → corriger sur erreur → max 3 essais → demander si bloqué
4. Emails : sobre, professionnel, signer "{USER_FIRSTNAME}"
5. Demande créative (API, BI, BDD) → proposer 3 approches, choisir la meilleure
6. Ambigu → UNE question de clarification seulement
7. Inconnu → "je ne sais pas" en 1 phrase, pas d'invention
8. Choisir toujours la meilleure bibliothèque/moteur pour la situation :
   - Analytics rapide → DuckDB
   - Dashboard web → Plotly
   - Stats distribution → Seaborn
   - Graphique PDF → Matplotlib + ReportLab
   - Gros volumes → Polars
"""

# ─────────────────────────────────────────────
# Définition des outils pour Claude
# ─────────────────────────────────────────────

TOOLS = [
    # ── EMAIL ──────────────────────────────────────────────────────────
    {
        "name": "read_emails",
        "description": "Lire les emails non lus Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Nombre d'emails (défaut 10)", "default": 10}
            }
        }
    },
    {
        "name": "draft_email",
        "description": "Rédiger un brouillon d'email affiché dans le chat avant envoi. Attend validation (bouton).",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Destinataire"},
                "subject": {"type": "string", "description": "Objet"},
                "body": {"type": "string", "description": "Corps de l'email"}
            },
            "required": ["to", "subject", "body"]
        }
    },
    # ── FICHIERS ───────────────────────────────────────────────────────
    {
        "name": "analyze_file",
        "description": "Analyser un fichier uploadé (Excel, CSV, Parquet) : résumé statistique, détection d'anomalies, graphiques, export PDF/Excel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Nom du fichier uploadé"},
                "task": {
                    "type": "string",
                    "enum": ["summary", "anomalies", "chart", "pdf", "excel", "all"],
                    "description": "summary | anomalies | chart | pdf | excel | all",
                    "default": "all"
                }
            },
            "required": ["filename"]
        }
    },
    # ── CODE MULTI-LANGAGE ─────────────────────────────────────────────
    {
        "name": "execute_code",
        "description": (
            "Écrire et exécuter du code multi-langage. "
            "Langages : python | javascript | typescript | sql | bash | r | ruby | php | powershell. "
            "Détection automatique si language non précisé. "
            "Retry automatique avec correction Claude (max 3 essais). "
            "SQL exécuté via DuckDB (ultra-rapide, in-memory)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code complet à exécuter"},
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "typescript", "sql",
                             "bash", "r", "ruby", "php", "powershell", "auto"],
                    "description": "Langage cible (auto = détection automatique)",
                    "default": "auto"
                },
                "description": {"type": "string", "description": "Description courte de la tâche"}
            },
            "required": ["code"]
        }
    },
    # ── BASES DE DONNÉES ───────────────────────────────────────────────
    {
        "name": "database_query",
        "description": (
            "Opérations multi-moteurs de bases de données. "
            "Moteurs : duckdb (analytics OLAP) | sqlite (local) | postgresql | mysql | mongodb. "
            "DuckDB peut interroger directement CSV/Parquet/JSON sans import. "
            "Actions : duckdb_sql | create_from_file | query | insert | detect_duplicates | report | list_tables | mongo_find | mongo_insert."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["duckdb_sql", "create_from_file", "query", "insert",
                             "detect_duplicates", "report", "list_tables",
                             "mongo_find", "mongo_insert", "mongo_update", "mongo_aggregate"],
                    "description": "Action à effectuer"
                },
                "engine": {
                    "type": "string",
                    "enum": ["duckdb", "sqlite", "postgresql", "mysql", "mongodb"],
                    "description": "Moteur de base de données",
                    "default": "sqlite"
                },
                "sql": {"type": "string", "description": "Requête SQL (pour duckdb_sql, query)"},
                "table": {"type": "string", "description": "Nom de la table"},
                "filename": {"type": "string", "description": "Fichier source (pour create_from_file)"},
                "data": {"type": "object", "description": "Données à insérer"},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Colonnes à vérifier (detect_duplicates)"
                },
                "db_url": {"type": "string", "description": "URL de connexion (postgresql://..., mysql://..., mongodb://...)"},
                "filter": {"type": "object", "description": "Filtre MongoDB"},
                "collection": {"type": "string", "description": "Collection MongoDB"},
                "limit": {"type": "integer", "description": "Limite de résultats", "default": 50}
            },
            "required": ["action"]
        }
    },
    # ── BI & REPORTING ────────────────────────────────────────────────
    {
        "name": "generate_bi_report",
        "description": (
            "Générer un rapport BI professionnel depuis une API ou un fichier uploadé. "
            "Graphiques Plotly (interactif) : bar, line, pie, scatter, area, funnel, treemap, waterfall, candlestick, gauge, histogram. "
            "Graphiques Seaborn (stats) : heatmap, boxplot, violin, pairplot, kde, regression. "
            "Graphiques Matplotlib (statique/PDF) : static_bar, static_line, static_pie. "
            "Exports : html (dashboard interactif) | pdf (ReportLab professionnel) | excel (mis en forme) | all. "
            "Planification cron avec APScheduler."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "api_url": {"type": "string", "description": "URL API source (optionnel si fichier)"},
                "api_key": {"type": "string", "description": "Clé API"},
                "auth_type": {
                    "type": "string",
                    "enum": ["bearer", "api_key", "basic", "none"],
                    "default": "bearer"
                },
                "title": {"type": "string", "description": "Titre du rapport"},
                "chart_configs": {
                    "type": "array",
                    "description": "Configuration des graphiques",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string",
                                     "description": "bar|line|pie|scatter|area|funnel|treemap|waterfall|candlestick|gauge|histogram|heatmap_corr|boxplot|violin|kde|regression"},
                            "x": {"type": "string", "description": "Colonne axe X"},
                            "y": {"type": "string", "description": "Colonne axe Y"},
                            "color": {"type": "string", "description": "Colonne couleur"},
                            "title": {"type": "string", "description": "Titre du graphique"}
                        }
                    }
                },
                "export": {
                    "type": "string",
                    "enum": ["html", "pdf", "excel", "all"],
                    "default": "html",
                    "description": "Format d'export"
                },
                "filename": {"type": "string", "description": "Fichier uploadé source"},
                "theme": {
                    "type": "string",
                    "enum": ["blue", "green", "dark"],
                    "default": "blue"
                },
                "schedule": {
                    "type": "string",
                    "description": "Cron expression (ex: '0 8 * * 1-5' = lundi-vendredi 8h)"
                }
            }
        }
    },
]

# ─────────────────────────────────────────────
# Cycle de vie Chainlit
# ─────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    """Initialisation de la session au démarrage du chat."""
    cl.user_session.set("history", [])
    cl.user_session.set("uploaded_files", {})
    cl.user_session.set("pending_email", None)

    await cl.Message(
        content=(
            f"👋 Bonjour **{USER_FIRSTNAME}** ! Je suis votre assistant IA polyvalent.\n\n"
            "**Ce que je peux faire :**\n"
            "- 📧 **Emails** — lire, rédiger et envoyer avec validation\n"
            "- 📊 **Excel/CSV** — analyser, détecter anomalies, générer graphiques\n"
            "- 🐍 **Code Python** — écrire, exécuter, corriger automatiquement\n"
            "- 🗄️ **Base de données** — SQLite : créer, interroger, détecter doublons\n"
            "- 📈 **Rapports BI** — dashboards depuis vos APIs, export PDF, planification\n\n"
            "**Exemples :**\n"
            "- *\"Lis mes emails non lus\"*\n"
            "- *Glisser un fichier .xlsx* → *\"Résume et trouve les anomalies\"*\n"
            "- *\"J'ai l'API Open-Meteo, propose 3 idées\"*\n"
            "- *\"Crée un rapport BI depuis mon API et envoie-le chaque matin\"*\n"
        )
    ).send()


# ─────────────────────────────────────────────
# Réception des messages
# ─────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message):
    """Traiter chaque message utilisateur."""
    history: list = cl.user_session.get("history", [])
    uploaded_files: dict = cl.user_session.get("uploaded_files", {})

    # ── 1. Sauvegarder les fichiers uploadés ──
    if message.elements:
        for element in message.elements:
            if hasattr(element, "path") and element.path:
                filename = element.name
                # Copier vers le dossier uploads
                upload_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    import shutil
                    shutil.copy2(element.path, upload_path)
                    uploaded_files[filename] = upload_path
                    cl.user_session.set("uploaded_files", uploaded_files)
                except Exception as e:
                    pass

    # ── 2. Ajouter le message à l'historique ──
    user_content = message.content or ""
    if message.elements:
        filenames = [e.name for e in message.elements if hasattr(e, "name")]
        if filenames:
            user_content += f"\n[Fichiers uploadés : {', '.join(filenames)}]"

    history.append({"role": "user", "content": user_content})

    # ── 3. Appel Claude avec streaming ──
    await _run_agent(history, uploaded_files)
    cl.user_session.set("history", history)


# ─────────────────────────────────────────────
# Boucle agent
# ─────────────────────────────────────────────

async def _run_agent(history: list, uploaded_files: dict):
    """
    Boucle agent : appel Claude → exécuter outils → renvoyer résultat → streaming.
    Supporte les appels d'outils multiples et chaînés.
    """
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # ── Appel Claude avec streaming ──
        msg = cl.Message(content="")
        await msg.send()

        full_text = ""
        tool_calls = []
        current_tool = None

        try:
            async with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=history,
            ) as stream:
                async for event in stream:
                    event_type = type(event).__name__

                    # Streaming du texte
                    if event_type == "RawContentBlockDeltaEvent":
                        delta = event.delta
                        delta_type = type(delta).__name__

                        if delta_type == "TextDelta" and hasattr(delta, "text"):
                            full_text += delta.text
                            await msg.stream_token(delta.text)

                        elif delta_type == "InputJSONDelta" and hasattr(delta, "partial_json"):
                            if current_tool:
                                current_tool["input_raw"] += delta.partial_json

                    elif event_type == "RawContentBlockStartEvent":
                        block = event.content_block
                        if hasattr(block, "type") and block.type == "tool_use":
                            current_tool = {
                                "id": block.id,
                                "name": block.name,
                                "input_raw": "",
                            }

                    elif event_type == "RawContentBlockStopEvent":
                        if current_tool:
                            try:
                                current_tool["input"] = json.loads(current_tool["input_raw"]) if current_tool["input_raw"] else {}
                            except json.JSONDecodeError:
                                current_tool["input"] = {}
                            tool_calls.append(current_tool)
                            current_tool = None

                # Récupérer le message final
                final = await stream.get_final_message()
                stop_reason = final.stop_reason

        except Exception as e:
            await msg.update()
            await cl.Message(content=f"❌ Erreur Claude : {e}").send()
            return

        # Mettre à jour le message
        if full_text:
            await msg.update()
        else:
            # Supprimer le message vide si Claude appelle seulement des outils
            msg.content = ""
            await msg.update()

        # ── Pas d'appels d'outils → fin ──
        if not tool_calls:
            if full_text:
                history.append({"role": "assistant", "content": full_text})
            return

        # ── Construire le contenu assistant avec les appels d'outils ──
        assistant_content = []
        if full_text:
            assistant_content.append({"type": "text", "text": full_text})
        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"],
            })

        history.append({"role": "assistant", "content": assistant_content})

        # ── Exécuter les outils ──
        tool_results = []
        for tc in tool_calls:
            result = await _execute_tool(tc["name"], tc["input"], uploaded_files)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": str(result),
            })

        history.append({"role": "user", "content": tool_results})

        # Si stop_reason est "end_turn" (pas d'outil), on arrête
        if stop_reason == "end_turn" and not tool_calls:
            return

    # Trop d'itérations
    await cl.Message(content="⚠️ Trop d'itérations dans la boucle agent.").send()


# ─────────────────────────────────────────────
# Dispatcher des outils
# ─────────────────────────────────────────────

async def _execute_tool(name: str, inputs: dict, uploaded_files: dict) -> str:
    """
    Exécuter un outil et retourner le résultat sous forme de chaîne.
    Affiche les étapes visibles dans le chat via cl.Step.
    """

    # ── 1. READ EMAILS ──────────────────────────────────────────────
    if name == "read_emails":
        count = inputs.get("count", 10)
        async with cl.Step(name="📬 Lecture des emails") as step:
            step.output = f"Récupération des {count} derniers emails non lus..."
            emails = await email_tool.read_emails(count=count)
            formatted = email_tool.format_email_list(emails)
            step.output = f"✅ {len([e for e in emails if 'id' in e])} email(s) récupéré(s)"

        await cl.Message(content=formatted).send()
        return json.dumps(emails, ensure_ascii=False, default=str)[:3000]


    # ── 2. DRAFT EMAIL ──────────────────────────────────────────────
    elif name == "draft_email":
        to = inputs.get("to", "")
        subject = inputs.get("subject", "")
        body = inputs.get("body", "")

        # Stocker le brouillon en attente
        cl.user_session.set("pending_email", {"to": to, "subject": subject, "body": body})

        # Afficher le brouillon avec boutons de validation
        draft_text = email_tool.format_draft(to, subject, body)

        actions = [
            cl.Action(name="send_email", label="✉️ Envoyer", payload={"confirm": True}),
            cl.Action(name="send_email", label="❌ Annuler", payload={"confirm": False}),
        ]

        await cl.Message(content=draft_text, actions=actions).send()
        return f"Brouillon affiché pour validation. En attente de la réponse utilisateur."

    # ── 3. ANALYZE FILE ────────────────────────────────────────────
    elif name == "analyze_file":
        filename = inputs.get("filename", "")
        task = inputs.get("task", "all")

        filepath = uploaded_files.get(filename)
        if not filepath:
            # Chercher dans le dossier uploads
            filepath = os.path.join(UPLOAD_DIR, filename)
            if not Path(filepath).exists():
                return f"Fichier '{filename}' introuvable. Uploader d'abord le fichier dans le chat."

        results = {}

        async with cl.Step(name=f"📊 Analyse — {filename}") as step:
            step.output = "Chargement du fichier..."

            if task in ("summary", "all"):
                step.output = "→ Calcul du résumé..."
                summary = await excel_tool.summarize(filepath)
                await cl.Message(content=summary).send()
                results["summary"] = "OK"

            if task in ("anomalies", "all"):
                step.output = "→ Détection des anomalies..."
                anomalies = await excel_tool.detect_anomalies(filepath)
                await cl.Message(content=anomalies).send()
                results["anomalies"] = "OK"

            if task in ("chart", "all"):
                step.output = "→ Génération du graphique..."
                chart_path = await excel_tool.generate_chart(filepath)
                if chart_path and Path(chart_path).exists():
                    await cl.Message(
                        content="📈 **Graphique généré :**",
                        elements=[cl.Image(name="chart.png", path=chart_path, display="inline")]
                    ).send()
                results["chart"] = chart_path or "Erreur"

            if task == "pdf":
                step.output = "→ Export PDF..."
                pdf_path = await excel_tool.export_pdf(filepath)
                if pdf_path and Path(pdf_path).exists():
                    await cl.Message(
                        content=f"📄 **Rapport PDF généré :** `{pdf_path}`",
                        elements=[cl.File(name=Path(pdf_path).name, path=pdf_path)]
                    ).send()
                results["pdf"] = pdf_path or "Erreur"

            step.output = "✅ Analyse terminée"

        return json.dumps(results)

    # ── 4. EXECUTE CODE (multi-langage) ──────────────────────────
    elif name == "execute_code":
        code = inputs.get("code", "")
        lang_hint = inputs.get("language", "auto")
        description = inputs.get("description", "Exécution")

        language = None if lang_hint in ("auto", "", None) else lang_hint
        detected = language or code_tool.detect_language(code)

        lang_icons = {
            "python": "🐍", "javascript": "🟨", "typescript": "🔷",
            "sql": "🗃️", "bash": "🖥️", "r": "📊", "powershell": "💠",
            "ruby": "💎", "php": "🐘",
        }
        icon = lang_icons.get(detected, "⚙️")

        async def fix_with_claude(bad_code: str, error: str, lang: str = detected) -> str:
            """Correction automatique via Claude."""
            fix_resp = await client.messages.create(
                model=MODEL, max_tokens=2048,
                messages=[{"role": "user", "content": (
                    f"Ce code {lang} produit une erreur. Corrige-le.\n\n"
                    f"```{lang}\n{bad_code}\n```\n\n"
                    f"Erreur :\n```\n{error}\n```\n\n"
                    f"Retourne UNIQUEMENT le code corrigé, sans explication ni markdown."
                )}]
            )
            corrected = fix_resp.content[0].text.strip()
            for marker in (f"```{lang}", "```python", "```js", "```sql", "```bash", "```"):
                if marker in corrected:
                    corrected = corrected.split(marker, 1)[1].split("```")[0].strip()
                    break
            return corrected

        async with cl.Step(name=f"{icon} {description} ({detected})") as step:
            step.output = f"→ {detected} — exécution..."
            result = await code_tool.execute_with_retry(
                code=code, description=description,
                language=language, hint=lang_hint if lang_hint != "auto" else None,
                fix_callback=fix_with_claude,
            )
            step.output = (
                f"✅ Succès en {result.get('exec_time', 0)}s"
                if result["success"]
                else f"❌ Échec après {result.get('attempts', 1)} essai(s)"
            )

        code_block = code_tool.code_block(code, detected)
        formatted = code_tool.format_result(result)
        await cl.Message(content=f"{code_block}\n\n{formatted}").send()

        # Afficher les fichiers générés (images, HTML)
        elements = []
        for line in (result.get("stdout") or "").split("\n"):
            p = line.strip()
            if p and Path(p).exists():
                if p.endswith((".png", ".jpg", ".svg")):
                    elements.append(cl.Image(name=Path(p).name, path=p, display="inline"))
                elif p.endswith(".html"):
                    elements.append(cl.File(name=Path(p).name, path=p))
        if elements:
            await cl.Message(content="📎 Fichiers générés :", elements=elements).send()

        return json.dumps({
            "success": result["success"],
            "language": result.get("language", detected),
            "stdout": (result.get("stdout") or "")[:500],
            "stderr": (result.get("stderr") or "")[:300],
            "attempts": result.get("attempts", 1),
        })

    # ── 5. DATABASE QUERY (multi-moteurs) ────────────────────────
    elif name == "database_query":
        action  = inputs.get("action", "")
        engine  = inputs.get("engine", "sqlite")
        table   = inputs.get("table", "")
        sql     = inputs.get("sql", "")
        data    = inputs.get("data", {})
        columns = inputs.get("columns", [])
        db_url  = inputs.get("db_url", None)
        filename = inputs.get("filename", "")
        collection = inputs.get("collection", "")
        fltr    = inputs.get("filter", {})
        limit   = inputs.get("limit", 50)

        engine_icons = {
            "duckdb": "🦆", "sqlite": "🗄️", "postgresql": "🐘",
            "mysql": "🐬", "mongodb": "🍃",
        }
        ei = engine_icons.get(engine, "🗄️")

        async with cl.Step(name=f"{ei} {engine.upper()} — {action}") as step:
            step.output = f"→ {action}..."
            result_text = ""
            import pandas as pd

            # ── DuckDB SQL analytique ────────────────────────────
            if action == "duckdb_sql":
                if not sql:
                    return "Requête SQL vide."
                # Injecter les fichiers uploadés comme contexte
                context = list(uploaded_files.values())
                db_result = await db_tool.duckdb_query(sql, context)
                if db_result["success"]:
                    result_text = f"🦆 **DuckDB** — {db_result['rowcount']} ligne(s)\n```\n{db_result.get('preview', '')}\n```"
                    step.output = f"✅ {db_result['rowcount']} lignes"
                else:
                    result_text = f"❌ {db_result.get('error', 'Erreur inconnue')}"
                    step.output = "❌ Erreur"

            # ── Créer depuis un fichier ──────────────────────────
            elif action == "create_from_file":
                filepath = uploaded_files.get(filename) or os.path.join(UPLOAD_DIR, filename)
                if not Path(filepath).exists():
                    return f"Fichier '{filename}' introuvable."
                file_res = await excel_tool.load_file(filepath)
                if not file_res["success"]:
                    return file_res["error"]
                tbl_name = table or Path(filename).stem
                db_result = await db_tool.create_from_dataframe(
                    file_res["dataframe"], tbl_name, engine, db_url
                )
                result_text = db_result.get("message") or db_result.get("error", "")
                step.output = f"✅ {result_text}"

            # ── Requête SQL ──────────────────────────────────────
            elif action == "query":
                if not sql:
                    return "Requête SQL vide."
                db_result = await db_tool.execute_query(sql, db_url=db_url, engine=engine)
                if db_result["success"]:
                    result_text = f"**{db_result['rowcount']} ligne(s)**\n```\n{db_result.get('preview', '')}\n```"
                else:
                    result_text = f"❌ {db_result.get('error', db_result.get('message'))}"
                step.output = f"✅ {db_result['rowcount']} ligne(s)" if db_result["success"] else "❌"

            # ── Insertion ────────────────────────────────────────
            elif action == "insert":
                if not table:
                    return "Nom de table requis."
                db_result = await db_tool.smart_insert(table, data, engine)
                result_text = db_result.get("message") or db_result.get("error", "")
                step.output = f"✅ {result_text}"

            # ── Doublons ─────────────────────────────────────────
            elif action == "detect_duplicates":
                if not table:
                    return "Nom de table requis."
                db_result = await db_tool.detect_duplicates(table, columns or None, engine, db_url)
                result_text = db_result.get("message", "")
                if db_result.get("preview"):
                    result_text += f"\n```\n{db_result['preview']}\n```"
                step.output = f"✅ {result_text[:80]}"

            # ── Rapport ──────────────────────────────────────────
            elif action == "report":
                result_text = await db_tool.generate_report(table or None, engine, db_url)
                step.output = "✅ Rapport généré"

            # ── Liste tables ─────────────────────────────────────
            elif action == "list_tables":
                tables = await db_tool.list_tables(engine, db_url)
                result_text = f"**Tables ({engine})** : {', '.join(f'`{t}`' for t in tables) if tables else '_(aucune)_'}"
                step.output = f"✅ {len(tables)} table(s)"

            # ── MongoDB ──────────────────────────────────────────
            elif action in ("mongo_find", "mongo_insert", "mongo_update", "mongo_aggregate"):
                mongo_action = action.replace("mongo_", "")
                db_result = await db_tool.mongo_query(
                    action=mongo_action, collection=collection,
                    filter=fltr, data=data, db_url=db_url, limit=limit
                )
                if db_result["success"]:
                    rows = db_result.get("rows", [])
                    result_text = f"🍃 MongoDB — {db_result['rowcount']} doc(s)"
                    if rows:
                        result_text += f"\n```json\n{json.dumps(rows[:5], indent=2, default=str, ensure_ascii=False)}\n```"
                else:
                    result_text = f"❌ {db_result.get('error', '')}"
                step.output = f"✅ {db_result['rowcount']} doc(s)" if db_result["success"] else "❌"

            else:
                result_text = f"Action inconnue : {action}"

        await cl.Message(content=result_text).send()
        return result_text

    # ── 6. GENERATE BI REPORT ─────────────────────────────────────
    elif name == "generate_bi_report":
        api_url      = inputs.get("api_url", "")
        api_key      = inputs.get("api_key", "")
        auth_type    = inputs.get("auth_type", "bearer")
        title        = inputs.get("title", "Rapport BI")
        chart_cfgs   = inputs.get("chart_configs", None)
        export       = inputs.get("export", "html")
        filename     = inputs.get("filename", "")
        theme        = inputs.get("theme", "blue")
        schedule     = inputs.get("schedule", "")

        import pandas as pd
        data_source = None

        try:
            async with cl.Step(name=f"📈 {title}") as step:

                # Chargement des données
                if filename:
                    fp = uploaded_files.get(filename) or os.path.join(UPLOAD_DIR, filename)
                    if not Path(fp).exists():
                        return f"Fichier '{filename}' introuvable."
                    step.output = f"→ Chargement {filename}..."
                    fr = await excel_tool.load_file(fp)
                    if not fr["success"]:
                        return fr["error"]
                    data_source = fr["dataframe"]
                    step.output = f"✅ {fr['info']['rows']} lignes chargées"

                elif api_url:
                    step.output = f"→ Appel API {api_url[:50]}..."
                    try:
                        fr = await bi_tool.fetch_api_data(url=api_url, api_key=api_key, auth_type=auth_type)
                        if not fr["success"]:
                            error_msg = f"Erreur API : {fr.get('error', 'Erreur inconnue')}"
                            step.output = f"❌ {error_msg}"
                            await cl.Message(content=f"❌ {error_msg}").send()
                            return error_msg
                        data_source = fr["data"]
                        step.output = "✅ Données récupérées"
                    except Exception as e:
                        error_msg = f"❌ Erreur lors de l'appel API : {str(e)}"
                        step.output = error_msg
                        await cl.Message(content=error_msg).send()
                        return error_msg
                else:
                    return "Fournir api_url ou uploader un fichier."

                if not isinstance(data_source, pd.DataFrame):
                    try:
                        data_source = bi_tool.normalize_data(data_source)
                    except Exception as e:
                        error_msg = f"❌ Erreur normalisation données : {str(e)}"
                        step.output = error_msg
                        await cl.Message(content=error_msg).send()
                        return error_msg

                if data_source is None or data_source.empty:
                    return "Impossible de convertir les données en tableau."

                step.output = f"→ Génération du rapport ({export})..."
                try:
                    bi_result = await bi_tool.full_report(
                        data=data_source, title=title,
                        api_url=api_url, chart_configs=chart_cfgs,
                        export=export, theme=theme,
                    )

                    if not bi_result["success"]:
                        error_msg = f"Erreur : {bi_result.get('error', 'Erreur inconnue')}"
                        step.output = f"❌ {error_msg}"
                        await cl.Message(content=f"❌ {error_msg}").send()
                        return error_msg

                    step.output = f"✅ {bi_result.get('shape', 'Généré')}"
                except Exception as e:
                    error_msg = f"❌ Erreur génération rapport : {str(e)}"
                    step.output = error_msg
                    await cl.Message(content=error_msg).send()
                    return error_msg

            # Afficher les fichiers
            msgs = [f"✅ **{title}** — {bi_result.get('shape', 'Généré')}"]
            elements = []
            for key, label, icon in [("html_path", "Dashboard HTML", "📊"), ("pdf_path", "PDF", "📄"), ("excel_path", "Excel", "📗")]:
                p = bi_result.get(key)
                if p and Path(p).exists():
                    elements.append(cl.File(name=Path(p).name, path=p))
                    msgs.append(f"{icon} {label} : `{p}`")

            await cl.Message(content="\n".join(msgs), elements=elements or None).send()

            # Planification
            if schedule and api_url:
                try:
                    sr = bi_tool.schedule_report(api_url=api_url, title=title, cron=schedule,
                                                  export=export, api_key=api_key)
                    await cl.Message(content=f"⏰ **Planifié :** {sr['message']}").send()
                except Exception as e:
                    await cl.Message(content=f"⚠️ Planification échouée : {str(e)}").send()

            return json.dumps({k: v for k, v in bi_result.items() if k not in ("data",)}, default=str)

        except Exception as e:
            error_msg = f"❌ Erreur BI report : {str(e)}"
            await cl.Message(content=error_msg).send()
            return error_msg

    return f"Outil inconnu : {name}"


# ─────────────────────────────────────────────
# Actions Chainlit (boutons de validation)
# ─────────────────────────────────────────────

@cl.action_callback("send_email")
async def on_send_email(action: cl.Action):
    """Callback des boutons Envoyer / Annuler pour les emails."""
    confirm = action.payload.get("confirm", False)
    pending = cl.user_session.get("pending_email")

    if not pending:
        await cl.Message(content="⚠️ Aucun email en attente.").send()
        return

    if confirm:
        async with cl.Step(name="✉️ Envoi de l'email") as step:
            step.output = f"→ Envoi à {pending['to']}..."
            result = await email_tool.send_email(
                to=pending["to"],
                subject=pending["subject"],
                body=pending["body"],
            )
            step.output = "✅ Envoyé" if result["success"] else f"❌ {result['message']}"

        if result["success"]:
            await cl.Message(content=f"✅ **Email envoyé** à `{pending['to']}`").send()
        else:
            await cl.Message(content=f"❌ Échec : {result['message']}").send()
    else:
        await cl.Message(content="🚫 **Envoi annulé.** L'email n'a pas été envoyé.").send()

    cl.user_session.set("pending_email", None)
    await action.remove()


# ─────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from chainlit.cli import run_chainlit
    run_chainlit(__file__)
