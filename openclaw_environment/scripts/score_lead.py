"""Score a stored lead against its campaign requirements."""
from __future__ import annotations

import argparse

from common import connect, now_iso
from lead_utils import score_lead


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute and persist a lead fit score")
    parser.add_argument("--lead-id", type=int, required=True)
    parser.add_argument("--threshold", type=int, default=60)
    parser.add_argument("--no-update", action="store_true")
    args = parser.parse_args()

    con = connect()
    lead = con.execute("SELECT * FROM leads WHERE id=?", (args.lead_id,)).fetchone()
    if not lead:
        raise SystemExit(f"ERROR: no lead with id {args.lead_id}")

    campaign = con.execute("SELECT * FROM campaigns WHERE id=?", (lead["campaign_id"],)).fetchone()
    if not campaign:
        raise SystemExit(f"ERROR: lead {args.lead_id} has no campaign")

    score, status, reasons = score_lead(con, lead, campaign, args.threshold)

    if not args.no_update:
        con.execute(
            """
            UPDATE leads
               SET fit_score=?,
                   status=?,
                   rejection_reason=?,
                   updated_at=?
             WHERE id=?
            """,
            (
                score,
                status,
                "; ".join(reasons) if status == "rejected" else None,
                now_iso(),
                args.lead_id,
            ),
        )
        con.commit()

    con.close()
    print(f"SCORE={score}")
    print(f"STATUS={status}")
    print(f"REASONS={'; '.join(reasons) if reasons else 'none'}")


if __name__ == "__main__":
    main()
