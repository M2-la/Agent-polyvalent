"""
email_tool.py — Lire et envoyer des emails
Supporte : Gmail OAuth2 (recommandé) ou SMTP simple
"""

import os
import smtplib
import base64
import json
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class EmailTool:
    """Outil email : lecture Gmail/SMTP + envoi avec confirmation."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
        self.token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")
        self._gmail_service = None

    # ─────────────────────────────────────────────
    # Gmail OAuth2
    # ─────────────────────────────────────────────

    def _get_gmail_service(self):
        """Initialiser le service Gmail via OAuth2."""
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            SCOPES = [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
            ]

            creds = None

            # Charger le token existant
            if Path(self.token_path).exists():
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

            # Rafraîchir ou authentifier
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                elif Path(self.credentials_path).exists():
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                else:
                    return None

                # Sauvegarder le token
                with open(self.token_path, "w") as token:
                    token.write(creds.to_json())

            self._gmail_service = build("gmail", "v1", credentials=creds)
            return self._gmail_service

        except ImportError:
            return None
        except Exception as e:
            print(f"[EmailTool] Erreur Gmail OAuth2 : {e}")
            return None

    # ─────────────────────────────────────────────
    # Lire les emails
    # ─────────────────────────────────────────────

    async def read_emails(self, count: int = 10) -> list[dict]:
        """
        Lire les emails non lus.
        Retourne une liste de dicts : {id, from, subject, date, snippet, body}
        """
        service = self._get_gmail_service()
        if service:
            return await asyncio.to_thread(self._read_gmail, service, count)
        else:
            return await asyncio.to_thread(self._read_smtp_fallback, count)

    def _read_gmail(self, service, count: int) -> list[dict]:
        """Lire via Gmail API."""
        emails = []
        try:
            # Récupérer les IDs des messages non lus
            results = service.users().messages().list(
                userId="me",
                labelIds=["UNREAD"],
                maxResults=count
            ).execute()

            messages = results.get("messages", [])

            for msg_ref in messages:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="full"
                ).execute()

                # Extraire les headers
                headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}

                # Extraire le corps
                body = self._extract_body(msg["payload"])

                emails.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", "(sans objet)"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                    "body": body[:2000],  # Limiter à 2000 chars
                })

        except Exception as e:
            emails = [{"error": f"Erreur lecture Gmail : {e}"}]

        return emails

    def _extract_body(self, payload: dict) -> str:
        """Extraire le corps d'un email (texte brut)."""
        body = ""

        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part["body"].get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                        break
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        return body

    def _read_smtp_fallback(self, count: int) -> list[dict]:
        """Fallback si Gmail OAuth2 non configuré."""
        return [{
            "info": "Gmail OAuth2 non configuré.",
            "instruction": "Copier credentials.json dans le dossier racine du projet. "
                           "Voir README.md section 'Configurer Gmail OAuth2'."
        }]

    # ─────────────────────────────────────────────
    # Envoyer un email
    # ─────────────────────────────────────────────

    async def send_email(self, to: str, subject: str, body: str) -> dict:
        """
        Envoyer un email via Gmail API ou SMTP.
        Retourne {success: bool, message: str}
        """
        service = self._get_gmail_service()
        if service:
            return await asyncio.to_thread(self._send_gmail, service, to, subject, body)
        elif self.smtp_user and self.smtp_password:
            return await asyncio.to_thread(self._send_smtp, to, subject, body)
        else:
            return {
                "success": False,
                "message": "Aucune méthode d'envoi configurée. "
                           "Configurer Gmail OAuth2 ou SMTP dans .env"
            }

    def _send_gmail(self, service, to: str, subject: str, body: str) -> dict:
        """Envoyer via Gmail API."""
        try:
            message = MIMEText(body, "plain", "utf-8")
            message["to"] = to
            message["subject"] = subject

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            service.users().messages().send(
                userId="me",
                body={"raw": raw}
            ).execute()

            return {"success": True, "message": f"Email envoyé à {to}"}

        except Exception as e:
            return {"success": False, "message": f"Erreur envoi Gmail : {e}"}

    def _send_smtp(self, to: str, subject: str, body: str) -> dict:
        """Envoyer via SMTP."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_user
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, to, msg.as_string())

            return {"success": True, "message": f"Email envoyé à {to}"}

        except Exception as e:
            return {"success": False, "message": f"Erreur envoi SMTP : {e}"}

    # ─────────────────────────────────────────────
    # Formater pour l'affichage dans le chat
    # ─────────────────────────────────────────────

    @staticmethod
    def format_email_list(emails: list[dict]) -> str:
        """Formater la liste d'emails pour affichage Chainlit."""
        if not emails:
            return "📭 Aucun email non lu."

        if "error" in emails[0] or "info" in emails[0]:
            return f"⚠️ {emails[0].get('error') or emails[0].get('info')}"

        lines = [f"📬 **{len(emails)} email(s) non lu(s)**\n"]
        for i, email in enumerate(emails, 1):
            lines.append(
                f"**{i}.** De : `{email['from']}`  \n"
                f"   Sujet : **{email['subject']}**  \n"
                f"   Date : {email['date']}  \n"
                f"   > {email['snippet'][:150]}...\n"
            )
        return "\n".join(lines)

    @staticmethod
    def format_draft(to: str, subject: str, body: str) -> str:
        """Formater le brouillon pour validation dans le chat."""
        return (
            f"📝 **Brouillon email — en attente de validation**\n\n"
            f"**À :** {to}  \n"
            f"**Objet :** {subject}  \n\n"
            f"---\n{body}\n---\n\n"
            f"*Cliquer sur **Envoyer** pour confirmer ou **Annuler** pour abandonner.*"
        )
