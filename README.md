# 🤖 Agent IA Polyvalent

Assistant personnel local avec interface chat Chainlit + Claude (Anthropic).

## Fonctionnalités

| Domaine | Ce que l'agent peut faire |
|---|---|
| 📧 **Emails** | Lire Gmail, rédiger des réponses, afficher le brouillon, envoyer après validation |
| 📊 **Excel/CSV** | Résumé, détection d'anomalies, graphiques Matplotlib, export PDF |
| 🐍 **Code Python** | Écrire, exécuter, corriger automatiquement (max 3 essais) |
| 🗄️ **SQLite** | Créer tables depuis fichiers, insérer, requêtes SQL, détecter doublons |
| 📈 **Rapports BI** | Dashboards HTML interactifs (Plotly), PDF, depuis APIs ou fichiers, planification automatique |

---

## Installation rapide

### 1. Prérequis

- Python 3.10 ou supérieur
- Un compte Anthropic avec clé API : https://console.anthropic.com

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer les variables d'environnement

```bash
cp .env.example .env
```

Ouvrir `.env` et renseigner au minimum :

```env
ANTHROPIC_API_KEY=sk-ant-...
USER_FIRSTNAME=Prénom
```

### 4. Lancer l'agent

```bash
chainlit run app.py
```

Ouvrir **http://localhost:8000** dans le navigateur.

---

## Configurer Gmail OAuth2

### Étape 1 — Créer un projet Google Cloud

1. Aller sur https://console.cloud.google.com
2. Créer un nouveau projet
3. Activer l'API Gmail : **APIs & Services → Bibliothèque → Gmail API → Activer**

### Étape 2 — Créer les identifiants OAuth2

1. **APIs & Services → Identifiants → Créer des identifiants → ID client OAuth**
2. Type d'application : **Application de bureau**
3. Télécharger le fichier JSON → le renommer `credentials.json`
4. Copier `credentials.json` à la racine du projet

### Étape 3 — Première authentification

Au premier lancement, un navigateur s'ouvre automatiquement pour autoriser l'accès Gmail.
Le token est sauvegardé dans `token.json` pour les prochaines fois.

> **Alternative SMTP** : renseigner `SMTP_USER` et `SMTP_PASSWORD` dans `.env`
> (mot de passe d'application Gmail : https://myaccount.google.com/apppasswords)

---

## Utilisation des rapports BI

### Depuis une API REST

Dans le chat :
```
J'ai l'API https://api.exemple.com/ventes — génère un dashboard avec des graphiques bar et line
```

### Depuis un fichier

Glisser-déposer un fichier `.xlsx` ou `.csv` puis :
```
Génère un rapport BI avec ce fichier, exporte en PDF
```

### Planifier un rapport automatique

```
Génère un rapport BI depuis https://api.exemple.com/data chaque matin à 8h
```

L'expression cron utilisée par défaut : `0 8 * * 1-5` (lundi-vendredi à 8h00)

### Configurer son API dans `.env`

```env
BI_API_URL=https://api.exemple.com/endpoint
BI_API_KEY=ma_cle_api
BI_API_HEADERS={"Authorization": "Bearer mon_token"}
BI_REPORT_SCHEDULE=0 8 * * 1-5
```

---

## Exemples de commandes dans le chat

```
Lis mes emails non lus
```
```
Réponds à Jean-Pierre : "Merci, je confirme le rendez-vous de jeudi"
```
```
[Glisser ventes.xlsx] Résume ce fichier et trouve les anomalies
```
```
[Glisser données.csv] Crée une table SQLite avec ce CSV et détecte les doublons
```
```
Écris un script Python qui appelle l'API wttr.in et affiche la météo de Paris
```
```
J'ai l'API Open-Meteo (https://api.open-meteo.com), propose 3 idées d'usage
```
```
Génère un dashboard BI depuis https://jsonplaceholder.typicode.com/users
```
```
Planifie un rapport BI chaque lundi à 9h depuis mon API
```

---

## Structure des fichiers

```
Agent-polyvalent/
├── app.py                  ← Point d'entrée Chainlit
├── requirements.txt        ← Dépendances Python
├── .env.example            ← Variables d'environnement (template)
├── .env                    ← Variables d'environnement (à créer)
├── .chainlit/
│   └── config.toml         ← Configuration Chainlit
├── tools/
│   ├── __init__.py
│   ├── email_tool.py       ← Emails Gmail/SMTP
│   ├── excel_tool.py       ← Analyse Excel/CSV
│   ├── code_tool.py        ← Exécution Python sécurisée
│   ├── db_tool.py          ← SQLite CRUD
│   └── bi_tool.py          ← Rapports BI + Plotly + planification
├── uploads/                ← Fichiers uploadés dans le chat
├── reports/                ← Rapports générés (HTML, PDF, PNG)
└── data/
    └── agent.db            ← Base SQLite
```

---

## Stack technique

| Composant | Librairie |
|---|---|
| Interface chat | `chainlit` |
| IA | `anthropic` (Claude claude-sonnet-4-6) |
| Excel/CSV | `pandas` + `openpyxl` |
| Graphiques interactifs | `plotly` |
| Graphiques statiques | `matplotlib` + `seaborn` |
| Export PDF | `fpdf2` |
| Base de données | `sqlite3` (inclus Python) |
| Requêtes HTTP | `aiohttp` |
| Gmail | `google-api-python-client` |
| Planification | `apscheduler` |

---

## Dépannage

**`ANTHROPIC_API_KEY` non trouvée**
→ Vérifier que le fichier `.env` existe et contient la clé

**Fichier uploadé non trouvé**
→ Le fichier doit être glissé-déposé directement dans le chat Chainlit

**Erreur Gmail OAuth2**
→ Vérifier que `credentials.json` est dans le dossier racine
→ Supprimer `token.json` pour ré-authentifier

**Rapport BI vide**
→ Vérifier que l'API retourne bien du JSON ou des données tabulaires
→ Utiliser `BI_API_HEADERS` dans `.env` si l'API nécessite une authentification

**APScheduler non disponible**
→ `pip install apscheduler`