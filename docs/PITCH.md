# FinVerify — Pitch & Compliance Narrative (Lab 1, Experian)

## The one-liner
LLMs are text engines, not calculators. FinVerify never trusts the model:
every number is re-computed deterministically in Python, every quote is
pinned verbatim to the source, and nothing renders until it has passed a
visible CI pipeline. **You just watched a machine refuse to believe itself.**

## Demo script (4 minutes)
1. Upload `sample_report.pdf`. Point at the pipeline: parse → redact →
   extract → verify-math → verify-citations → release. Real timings,
   measured counts. "Nothing you see skipped verification — structurally."
2. The MISMATCH card fires: stated RM 2,750,000 vs computed RM 2,650,000.
   "The model once set its own expected value and graded its own homework
   — we caught that live, and now every check must compare against a
   *cited* fact."
3. The trend check passes at exactly 10.0%; risks appear, each citing its
   evidence facts. Uncited risks are discarded before display.
4. Open "What left this machine": redacted text, mask counts. Click Clear
   Session — upload deleted from disk.
5. Invite a judge to upload their own PDF. If the API dies, the CACHED
   banner says so on screen — we don't fake a live call, ever.

## Decision → scoring criterion
| Decision | Criterion it wins |
|---|---|
| Fixed-op verifier, zero `eval` (grep-provable) | Responsible AI, accuracy |
| `against_fact_id` — no self-graded checks | Accuracy, explainability |
| Verbatim-quote citation pinning | Explainability, accuracy |
| In-product CI gate, streamed & measured | Explainability, UX |
| Trends verified like any other check; risks must cite evidence | Quality of insights |
| Layered PII redaction + validated NRIC, no bare-12-digit rule | PDPA |
| Redaction diff + purge + retention = request duration | PDPA, user control |
| Honest CACHED fallback, test-proven with the key removed | Responsible AI |
| Test-first history + CI on every push (grep the log) | Scalability/engineering |

## Judge Q&A — rehearsed answers
**"What's your lawful basis for sending data overseas?"** (Asmah)
The s.129 whitelist regime was removed on 1 April 2025; transfers now need
adequacy or safeguards. Our answer is simpler: only redacted operational
text leaves the machine — NRIC (date-validated), emails, phones, titled/
patronymic/cue names, and the PDF /Author name are masked first, and the
exact transmitted payload is inspectable on screen. The file itself never
leaves. Residual risk is stated, not hidden: bare untitled names and
scanned-image PII are out of regex reach — that's the known-limits line in
the UI, and the roadmap answer is NER, not more regex.

**"Can I upload my own PDF?"** (Spyros) — Yes. That's the demo. If it's
encrypted or scanned, the pipeline halts at parse with the reason shown
and later stages struck through — graceful, visible failure.

**"LLMs hallucinate — why should I trust this?"** (Syeda) — Don't trust
it; that's the design. Two independent gates: arithmetic recomputed in
Python, and every operand's quote string-matched into the source. We
demonstrate the failure live: the model's own self-graded check was caught
by the verifier during development, and the fix is in the git history.

**"Why not just use the model's answer?"** (Faiz) — Because a wrong
financial number costs real money at Experian's scale. The verification
layer is the product; the model is a replaceable parser (we swapped
Gemini→DeepSeek in one commit, test-first).

## Stated limits (say them before they're found)
- Bare names with no title/patronymic/cue are not redacted.
- Scanned-image PII is invisible to text extraction (no OCR).
- Three fixed operations; exotic arithmetic returns UNVERIFIABLE, never a
  guess.
- The live model path depends on one vendor API; the fallback is honest
  and visibly flagged.
