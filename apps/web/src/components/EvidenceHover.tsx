import { useState } from "react";

type Ev = { evidence_id: string; source?: string; title?: string; text?: string; date?: string | null; outcome?: string | null };
export type ClaimWithEvidence = { text: string; evidence: Ev[] };

/** A claim in the draft; hover or focus shows the portfolio evidence behind it (or that there is none). */
export function EvidenceHover({ claim }: { claim: ClaimWithEvidence }) {
  const [open, setOpen] = useState(false);
  const none = claim.evidence.length === 0;
  return (
    <span
      className={`claim ${none ? "unsupported" : ""}`}
      tabIndex={0}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? `ev-${claim.text.slice(0, 12)}` : undefined}
      data-testid="claim"
    >
      {claim.text}
      {open && (
        <span className="pop" role="tooltip" id={`ev-${claim.text.slice(0, 12)}`}>
          {none ? (
            <strong style={{ color: "var(--bad)" }}>No evidence linked to this claim.</strong>
          ) : (
            claim.evidence.map((e) => (
              <span key={e.evidence_id} style={{ display: "block", marginBottom: 8 }}>
                <span className="badge info">{e.source ?? e.evidence_id}</span>{" "}
                {e.date && <span className="small muted">{e.date}</span>}{" "}
                {e.outcome && <span className="badge">{e.outcome}</span>}
                <span style={{ display: "block", marginTop: 4 }}>{(e.text ?? "").slice(0, 320)}</span>
                <span className="mono muted">{e.evidence_id}</span>
              </span>
            ))
          )}
        </span>
      )}
    </span>
  );
}
