"""
db_tool.py — Multi-moteurs de base de données
Moteurs supportés :
  - DuckDB   ★ Analytics OLAP, SQL sur CSV/Parquet/JSON, in-memory
  - SQLite     Local, léger, embarqué (défaut)
  - PostgreSQL Production, ACID, JSON, full-text search
  - MySQL      Web, compatibilité large
  - MongoDB    Documents NoSQL, schéma flexible

Connexion par URL :
  duckdb:///:memory:        (in-memory)
  duckdb:///path/data.duckdb
  sqlite:///data/agent.db
  postgresql://user:pass@host:5432/dbname
  mysql://user:pass@host:3306/dbname
  mongodb://user:pass@host:27017/dbname
"""

import os
import asyncio
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB = os.getenv("DB_PATH", "data/agent.db")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "data/analytics.duckdb")


class DatabaseTool:
    """Outil multi-DB : DuckDB, SQLite, PostgreSQL, MySQL, MongoDB."""

    def __init__(self):
        Path("data").mkdir(parents=True, exist_ok=True)
        self._connections: dict = {}  # cache de connexions

    # ─────────────────────────────────────────────
    # Connexion universelle par URL
    # ─────────────────────────────────────────────

    def _parse_engine(self, db_url: str) -> str:
        """Extraire le type de moteur depuis l'URL."""
        if db_url.startswith("duckdb"):
            return "duckdb"
        if db_url.startswith("sqlite") or db_url.endswith(".db") or db_url.endswith(".sqlite"):
            return "sqlite"
        if db_url.startswith("postgresql") or db_url.startswith("postgres"):
            return "postgresql"
        if db_url.startswith("mysql") or db_url.startswith("mariadb"):
            return "mysql"
        if db_url.startswith("mongodb") or db_url.startswith("mongo"):
            return "mongodb"
        return "sqlite"  # défaut

    def _get_sqlite(self, path: str = None):
        import sqlite3
        db_path = path or DEFAULT_DB
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _get_duckdb(self, path: str = None):
        import duckdb
        db_path = path or DUCKDB_PATH
        if ":memory:" in str(db_path):
            return duckdb.connect(":memory:")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(db_path)

    def _get_postgres(self, url: str):
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn

    def _get_mysql(self, url: str):
        import pymysql
        import pymysql.cursors
        # Parser l'URL mysql://user:pass@host:port/db
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
        )

    def _get_mongo(self, url: str):
        from pymongo import MongoClient
        from urllib.parse import urlparse
        parsed = urlparse(url)
        db_name = parsed.path.lstrip("/") or "agent"
        client = MongoClient(url)
        return client, client[db_name]

    # ─────────────────────────────────────────────
    # ★ DuckDB Analytics — SQL sur fichiers directs
    # ─────────────────────────────────────────────

    async def duckdb_query(self, sql: str, context_files: list[str] = None) -> dict:
        """
        Exécuter du SQL analytique via DuckDB.
        DuckDB peut lire directement CSV, Parquet, JSON sans import préalable.

        Exemple : SELECT * FROM 'data/ventes.csv' WHERE montant > 1000
        """
        return await asyncio.to_thread(self._duckdb_query_sync, sql, context_files)

    def _duckdb_query_sync(self, sql: str, context_files: list[str] = None) -> dict:
        try:
            import duckdb
            conn = duckdb.connect(":memory:")

            # Extensions utiles
            try:
                conn.execute("INSTALL httpfs; LOAD httpfs;")
            except Exception:
                pass

            # Créer des vues pour les fichiers contextuels
            if context_files:
                for fp in context_files:
                    p = Path(fp)
                    if p.exists():
                        view_name = p.stem.replace("-", "_").replace(" ", "_")
                        if p.suffix.lower() == ".csv":
                            conn.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_csv_auto('{fp}')")
                        elif p.suffix.lower() in (".parquet", ".pq"):
                            conn.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_parquet('{fp}')")
                        elif p.suffix.lower() == ".json":
                            conn.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_json_auto('{fp}')")

            result = conn.execute(sql)
            rows = result.fetchall()
            cols = [d[0] for d in result.description] if result.description else []

            # Formater
            import pandas as pd
            if rows:
                df = pd.DataFrame(rows, columns=cols)
                return {"success": True, "rows": rows, "columns": cols,
                        "dataframe": df, "rowcount": len(rows),
                        "preview": df.head(20).to_string(index=False)}
            return {"success": True, "rows": [], "columns": cols,
                    "rowcount": 0, "preview": "(0 résultats)"}

        except Exception as e:
            return {"success": False, "error": str(e), "rows": [], "columns": []}

    # ─────────────────────────────────────────────
    # Requête universelle (SQLite + PostgreSQL + MySQL)
    # ─────────────────────────────────────────────

    async def execute_query(
        self,
        sql: str,
        params: tuple = (),
        db_url: str = None,
        engine: str = "sqlite",
    ) -> dict:
        """
        Exécuter une requête SQL sur n'importe quel moteur.
        db_url prioritaire sur engine.
        """
        if db_url:
            engine = self._parse_engine(db_url)

        if engine == "duckdb":
            return await self.duckdb_query(sql)

        return await asyncio.to_thread(self._query_sync, sql, params, db_url, engine)

    def _query_sync(self, sql: str, params: tuple, db_url: str, engine: str) -> dict:
        try:
            if engine == "sqlite":
                conn = self._get_sqlite(db_url.replace("sqlite:///", "") if db_url else None)
                cursor = conn.execute(sql, params)
            elif engine == "postgresql":
                conn = self._get_postgres(db_url)
                cursor = conn.cursor()
                cursor.execute(sql, params)
            elif engine == "mysql":
                conn = self._get_mysql(db_url)
                cursor = conn.cursor()
                cursor.execute(sql, params)
            else:
                return {"success": False, "error": f"Moteur inconnu : {engine}"}

            sql_upper = sql.strip().upper()
            is_select = sql_upper.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN"))

            if is_select:
                if engine == "sqlite":
                    rows = [dict(r) for r in cursor.fetchall()]
                    cols = [d[0] for d in cursor.description] if cursor.description else []
                else:
                    rows = cursor.fetchall()
                    rows = [dict(r) for r in rows] if rows else []
                    cols = list(rows[0].keys()) if rows else []

                import pandas as pd
                df = pd.DataFrame(rows) if rows else pd.DataFrame()
                return {
                    "success": True, "rows": rows, "columns": cols,
                    "rowcount": len(rows), "engine": engine,
                    "preview": df.head(20).to_string(index=False) if not df.empty else "(vide)",
                }
            else:
                conn.commit()
                affected = cursor.rowcount
                return {"success": True, "rows": [], "columns": [],
                        "rowcount": affected, "engine": engine,
                        "preview": f"{affected} ligne(s) affectée(s)"}

        except Exception as e:
            return {"success": False, "error": str(e), "rows": [], "columns": []}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # MongoDB
    # ─────────────────────────────────────────────

    async def mongo_query(
        self,
        action: str,
        collection: str,
        filter: dict = None,
        data: dict | list = None,
        db_url: str = None,
        limit: int = 50,
    ) -> dict:
        """
        Opérations MongoDB.
        action : find | insert | update | delete | aggregate | count | distinct
        """
        return await asyncio.to_thread(
            self._mongo_sync, action, collection, filter or {}, data, db_url, limit
        )

    def _mongo_sync(self, action, collection, filter, data, db_url, limit) -> dict:
        try:
            url = db_url or os.getenv("MONGODB_URL", "mongodb://localhost:27017/agent")
            client, db = self._get_mongo(url)
            coll = db[collection]

            if action == "find":
                docs = list(coll.find(filter, limit=limit))
                for d in docs:
                    d["_id"] = str(d["_id"])
                return {"success": True, "rows": docs, "rowcount": len(docs)}

            elif action == "insert":
                if isinstance(data, list):
                    result = coll.insert_many(data)
                    return {"success": True, "rowcount": len(result.inserted_ids)}
                else:
                    result = coll.insert_one(data)
                    return {"success": True, "rowcount": 1, "id": str(result.inserted_id)}

            elif action == "update":
                result = coll.update_many(filter, {"$set": data})
                return {"success": True, "rowcount": result.modified_count}

            elif action == "delete":
                result = coll.delete_many(filter)
                return {"success": True, "rowcount": result.deleted_count}

            elif action == "count":
                n = coll.count_documents(filter)
                return {"success": True, "rowcount": n}

            elif action == "aggregate":
                # data = pipeline
                result = list(coll.aggregate(data or []))
                for d in result:
                    d["_id"] = str(d.get("_id", ""))
                return {"success": True, "rows": result, "rowcount": len(result)}

            else:
                return {"success": False, "error": f"Action MongoDB inconnue : {action}"}

        except ImportError:
            return {"success": False, "error": "pymongo non installé. pip install pymongo"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                client.close()
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # Créer une table depuis un DataFrame
    # ─────────────────────────────────────────────

    async def create_from_dataframe(
        self, df, table: str, engine: str = "sqlite", db_url: str = None,
        if_exists: str = "replace"
    ) -> dict:
        """
        Créer une table et y insérer un DataFrame.
        if_exists : replace | append | fail
        """
        return await asyncio.to_thread(
            self._create_from_df_sync, df, table, engine, db_url, if_exists
        )

    def _create_from_df_sync(self, df, table, engine, db_url, if_exists) -> dict:
        try:
            if engine == "duckdb":
                import duckdb
                path = (db_url.replace("duckdb:///", "") if db_url else DUCKDB_PATH)
                if ":memory:" in str(path):
                    conn = duckdb.connect(":memory:")
                else:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    conn = duckdb.connect(path)
                conn.register("_tmp_df", df)
                if if_exists == "replace":
                    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
                conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" AS SELECT * FROM _tmp_df')
                count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                conn.close()
                return {"success": True, "rowcount": count,
                        "message": f"Table `{table}` créée dans DuckDB avec {count} lignes."}

            else:
                # SQLite, PostgreSQL, MySQL via SQLAlchemy
                from sqlalchemy import create_engine
                if not db_url:
                    db_url = f"sqlite:///{DEFAULT_DB}"
                eng = create_engine(db_url)
                df.to_sql(table, eng, if_exists=if_exists, index=False, chunksize=1000)
                return {"success": True, "rowcount": len(df),
                        "message": f"Table `{table}` créée avec {len(df)} lignes ({engine})."}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────
    # Détecter les doublons
    # ─────────────────────────────────────────────

    async def detect_duplicates(
        self, table: str, columns: list[str] = None,
        engine: str = "sqlite", db_url: str = None
    ) -> dict:
        """Détecter les doublons dans une table."""
        return await asyncio.to_thread(
            self._detect_dupes_sync, table, columns, engine, db_url
        )

    def _detect_dupes_sync(self, table, columns, engine, db_url) -> dict:
        try:
            if engine == "duckdb":
                import duckdb
                path = db_url.replace("duckdb:///", "") if db_url else DUCKDB_PATH
                conn = duckdb.connect(path if ":memory:" not in str(path) else ":memory:")
                info = conn.execute(f"DESCRIBE {table}").fetchall()
                cols = columns or [row[0] for row in info]
            else:
                conn = self._get_sqlite(db_url.replace("sqlite:///", "") if db_url else None)
                info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                cols = columns or [row[1] for row in info if row[1] != "id"]

            if not cols:
                return {"success": False, "error": f"Table `{table}` vide ou introuvable."}

            col_list = ", ".join([f'"{c}"' for c in cols])
            sql = f"""
                SELECT {col_list}, COUNT(*) as n_doublons
                FROM "{table}"
                GROUP BY {col_list}
                HAVING COUNT(*) > 1
                ORDER BY n_doublons DESC
                LIMIT 30
            """

            if engine == "duckdb":
                result = conn.execute(sql)
                dupes = result.fetchall()
                dupe_cols = [d[0] for d in result.description] if result.description else []
            else:
                cursor = conn.execute(sql)
                dupes = cursor.fetchall()
                dupe_cols = cols + ["n_doublons"]

            total_sql = f"""
                SELECT COALESCE(SUM(n - 1), 0) FROM (
                    SELECT COUNT(*) as n FROM "{table}"
                    GROUP BY {col_list}
                    HAVING COUNT(*) > 1
                )
            """
            if engine == "duckdb":
                total_extra = conn.execute(total_sql).fetchone()[0] or 0
            else:
                total_extra = conn.execute(total_sql).fetchone()[0] or 0

            import pandas as pd
            df_dupes = pd.DataFrame(dupes, columns=dupe_cols) if dupes else pd.DataFrame()

            return {
                "success": True,
                "duplicate_groups": len(dupes),
                "total_extra_rows": int(total_extra),
                "columns_checked": cols,
                "preview": df_dupes.to_string(index=False) if not df_dupes.empty else "",
                "message": (
                    f"{len(dupes)} groupe(s) de doublons, {int(total_extra)} ligne(s) en trop."
                    if dupes else "✅ Aucun doublon détecté."
                )
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────
    # Rapport de synthèse universel
    # ─────────────────────────────────────────────

    async def generate_report(
        self, table: str = None, engine: str = "sqlite", db_url: str = None
    ) -> str:
        """Rapport de synthèse complet de la base de données."""
        return await asyncio.to_thread(self._report_sync, table, engine, db_url)

    def _report_sync(self, table, engine, db_url) -> str:
        lines = []
        try:
            if engine == "duckdb":
                import duckdb
                path = db_url.replace("duckdb:///", "") if db_url else DUCKDB_PATH
                conn = duckdb.connect(path if ":memory:" not in str(path) else ":memory:")
                tables_result = conn.execute("SHOW TABLES").fetchall()
                tables = [r[0] for r in tables_result]
                lines.append(f"🦆 **DuckDB** — `{path}`")
            else:
                import sqlite3
                path = db_url.replace("sqlite:///", "") if db_url else DEFAULT_DB
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                tables_result = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                tables = [r[0] for r in tables_result]
                lines.append(f"🗄️ **SQLite** — `{path}`")

            if not tables:
                return "\n".join(lines) + "\n\n_Base de données vide._"

            lines.append(f"**{len(tables)} table(s) :** {', '.join(f'`{t}`' for t in tables)}\n")

            target = [table] if table and table in tables else tables
            for tbl in target:
                if engine == "duckdb":
                    count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    info = conn.execute(f'DESCRIBE "{tbl}"').fetchall()
                    cols = [f"`{r[0]}` ({r[1]})" for r in info]
                    sample = conn.execute(f'SELECT * FROM "{tbl}" LIMIT 5').fetchdf()
                else:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    info = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                    cols = [f"`{r[1]}` ({r[2]})" for r in info]
                    import pandas as pd
                    cursor = conn.execute(f'SELECT * FROM "{tbl}" LIMIT 5')
                    col_names = [d[0] for d in cursor.description]
                    rows = cursor.fetchall()
                    sample = pd.DataFrame([dict(zip(col_names, r)) for r in rows])

                lines.append(f"---\n**`{tbl}`** — {count:,} ligne(s)")
                lines.append(f"Colonnes : {', '.join(cols)}")
                if not sample.empty:
                    lines.append("```\n" + sample.to_string(index=False) + "\n```")

            conn.close()
            return "\n".join(lines)

        except Exception as e:
            return f"❌ Erreur rapport : {e}"

    # ─────────────────────────────────────────────
    # Utilitaires
    # ─────────────────────────────────────────────

    async def list_tables(self, engine: str = "sqlite", db_url: str = None) -> list[str]:
        """Lister les tables d'une base."""
        return await asyncio.to_thread(self._list_tables_sync, engine, db_url)

    def _list_tables_sync(self, engine, db_url) -> list[str]:
        try:
            if engine == "duckdb":
                import duckdb
                path = db_url.replace("duckdb:///", "") if db_url else DUCKDB_PATH
                conn = duckdb.connect(path)
                result = conn.execute("SHOW TABLES").fetchall()
                conn.close()
                return [r[0] for r in result]
            else:
                import sqlite3
                path = db_url.replace("sqlite:///", "") if db_url else DEFAULT_DB
                if not Path(path).exists():
                    return []
                conn = sqlite3.connect(path)
                result = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                conn.close()
                return [r[0] for r in result]
        except Exception:
            return []

    async def smart_insert(self, table: str, data: dict | list, engine: str = "sqlite") -> dict:
        """Insérer en détectant automatiquement si la table existe."""
        return await asyncio.to_thread(self._smart_insert_sync, table, data, engine)

    def _smart_insert_sync(self, table, data, engine) -> dict:
        try:
            import pandas as pd
            rows = [data] if isinstance(data, dict) else data
            df = pd.DataFrame(rows)

            import sqlite3
            conn = sqlite3.connect(DEFAULT_DB)
            df.to_sql(table, conn, if_exists="append", index=False)
            conn.close()
            return {"success": True, "rowcount": len(rows),
                    "message": f"{len(rows)} ligne(s) insérée(s) dans `{table}`."}
        except Exception as e:
            return {"success": False, "error": str(e)}
