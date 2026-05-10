from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from common import connect, now_iso
from extract_contact import extract_contact
from init_db import init
from lead_utils import compliance_check
from parse_campaign import parse_campaign
from provider_client import DEFAULT_PROVIDER_MCP_URL


class RequirementTests(unittest.TestCase):
    def test_parse_campaign_from_natural_language(self):
        params = parse_campaign(
            "Find 50 restaurants in Paris, France and write personalized outreach emails "
            "offering my explainer video service."
        )

        self.assertEqual(params["target_count"], 50)
        self.assertEqual(params["niche"], "restaurants")
        self.assertEqual(params["location"], "Paris, France")
        self.assertEqual(params["offer"], "explainer video service")
        self.assertEqual(params["language"], "en")
        self.assertTrue(params["approval_required"])
        self.assertEqual(params["daily_send_limit"], 25)

    def test_contact_extraction_preserves_public_source_and_address(self):
        html = """
        <html>
          <head><title>Example Dental Clinic</title></head>
          <body>
            <h1>Example Dental Clinic</h1>
            <address>10 Main Street, Austin, TX</address>
            <a href="mailto:hello@exampleclinic.com">Email us</a>
          </body>
        </html>
        """

        data = extract_contact(html, "https://exampleclinic.com/contact")

        self.assertEqual(data["business_name"], "Example Dental Clinic")
        self.assertEqual(data["emails"], ["hello@exampleclinic.com"])
        self.assertEqual(data["email_source_url"], "https://exampleclinic.com/contact")
        self.assertEqual(data["address"], "10 Main Street, Austin, TX")

    def test_compliance_enforces_documented_word_count_and_opt_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OUTREACH_DB_PATH"] = os.path.join(tmp, "outreach.db")
            init(os.environ["OUTREACH_DB_PATH"])
            con = connect()
            cur = con.execute(
                """
                INSERT INTO campaigns (
                    niche, location, target, target_count, offer, language,
                    approval_required, daily_send_limit, status, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                ("dentists", "Austin", 10, 10, "website design", "en", 1, 25, "draft", now_iso()),
            )
            campaign_id = cur.lastrowid
            cur = con.execute(
                """
                INSERT INTO leads (
                    campaign_id, name, url, email, context, status,
                    business_name, website_url, contact_page_url, description,
                    source_url, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    campaign_id,
                    "Example Dental Clinic",
                    "https://exampleclinic.com",
                    "hello@exampleclinic.com",
                    "Example Dental Clinic offers family dental care in Austin.",
                    "new",
                    "Example Dental Clinic",
                    "https://exampleclinic.com",
                    "https://exampleclinic.com/contact",
                    "Example Dental Clinic offers family dental care in Austin.",
                    "https://exampleclinic.com/contact",
                    now_iso(),
                ),
            )
            lead = con.execute("SELECT * FROM leads WHERE id=?", (cur.lastrowid,)).fetchone()

            short_body = (
                "Hi Example Dental Clinic team, I noticed your Austin dental care. "
                "Would you like help? If this is not relevant, reply \"no\" and I will not follow up."
            )
            status, reason = compliance_check(con, lead, "Idea for Example Dental Clinic", short_body)
            self.assertEqual(status, "failed")
            self.assertIn("80-word minimum", reason)

            body = (
                "Hi Example Dental Clinic team,\n\n"
                "I noticed Example Dental Clinic offers family dental care in Austin, which gives local patients "
                "a clear sense of the care they can expect before they book an appointment.\n\n"
                "I help clinics with website design that makes key services, trust signals, and appointment options "
                "easier to understand for nearby patients who are comparing providers online.\n\n"
                "Would you be open to a quick reply if this is relevant? If this is not relevant, reply \"no\" "
                "and I will not follow up.\n\n"
                "Thanks"
            )
            status, reason = compliance_check(con, lead, "Idea for Example Dental Clinic", body)
            con.close()
            os.environ.pop("OUTREACH_DB_PATH", None)

        self.assertEqual((status, reason), ("passed", "ok"))

    def test_agent_side_scripts_do_not_access_provider_credentials_directly(self):
        banned = [
            "smtplib",
            "imaplib",
            'os.environ.get("SMTP_',
            'os.environ.get("IMAP_',
            'os.environ.get("SERPAPI_',
            'os.environ.get("BING_',
        ]
        for path in Path(SCRIPTS).glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for pattern in banned:
                self.assertNotIn(pattern, source, f"{path.name} must use provider_client instead of {pattern}")

    def test_agent_uses_provider_mcp_url_not_local_credentials(self):
        self.assertEqual(DEFAULT_PROVIDER_MCP_URL, "http://127.0.0.1:8770/mcp")


if __name__ == "__main__":
    unittest.main()
