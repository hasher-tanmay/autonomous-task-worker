# Evaluation evidence

**Observed result: 18/18 browser integration checks and 10/10 real-model scenarios passed.**

Tested on October 4, 2026 using **OpenAI `gpt-4.1-mini`**, real Chromium, an HTTP company portal and SQLite. The final video separately records the Gradio interface with Model planner selected. No planner or browser responses were mocked in the model evaluation.

This supports the eight criteria within the stated invoice sandbox. It does **not** prove perfect reliability or generalization to arbitrary websites. Engineering quality and technical understanding also require human review and discussion.

| Criterion | Concrete evidence | Boundary |
|---|---|---|
| Autonomy | A previously unlisted phrase, “Find the newest bill ... register it,” becomes a record/latest goal. The API model chooses next actions from observations. | High-level tools and legal actions are constrained by code; this is not unrestricted desktop autonomy. |
| Execution | Chromium follows invoice links, fills the ledger form and clicks Save. Records actually persist in SQLite. | The portal and invoices are synthetic. |
| Reliability | Transient save: two attempts. Lost acknowledgement: one attempt, one row. Permanent outage: failure after three attempts. Approval decline: no row. Missing field: clarification. | A bounded failure is a correct outcome, not successful task completion. |
| Verification | Reloaded fields must match the observed source. Corrupted USD 0.01 persistence is rejected. Independent checks also confirmed expected row IDs, amounts and due dates in the evaluation results. | Conflicting records need manual review; no automatic repair or rollback. |
| Generalization | Latest/all, record/report and three valid vendors use the same engine and tools. Reporting leaves the ledger empty. | One vendor per task, one portal, USD only. |
| Engineering quality | Small planner/executor/verifier separation; typed actions; bounded budgets; unique database key; explicit database cleanup; real browser integration tests and CI configuration. | CI configuration is supplied; local passing tests do not establish that remote CI has run. |
| Product thinking | Goals produce verified results and downloadable evidence. High-value writes ask for approval; unsupported payments and incomplete sources stop clearly. | No production authorization, payments or real inbox integration. |
| Technical understanding | The video explains component responsibilities, why reconciliation precedes retry, why completion belongs to the verifier, and known limitations. README describes design decisions and components. | Understanding must still be demonstrated by the submitter in the technical discussion. |

## Real-model scenario outcomes

| Scenario | Observed outcome | Key check |
|---|---|---|
| Natural wording + transient failure | Completed | X-101; two save attempts; exact amount/due date |
| Lost acknowledgement | Completed | One save attempt; one persisted row |
| Multiple invoices | Completed | X-100 and X-101; both verified |
| Read-only different vendor | Completed | Acme source read; zero ledger rows |
| Approval and resume | Completed | Zero rows before approval; N-301 after approval |
| Approval declined | Cancelled | Zero ledger rows |
| Missing source fields | Needs clarification | No invented due date; zero ledger rows |
| Permanent failure | Failed as expected | Three save attempts; zero rows |
| Corrupted persistence | Failed as expected | Mismatch detected; no verified completion |
| Unsupported payment request | Needs clarification | No payment tools or ledger rows |

Machine-readable observations are in `model-evaluation.json`, including the trace, persisted rows, retries, model identifier and timings. The results are a single measured run of ten scenarios, not a statistical benchmark. Model behavior can vary between runs.

## Debugging decisions

The first real-model run passed 8/10. The read-only goal repeatedly proposed saves; the host guard prevented every write. A permanent outage was classified as clarification after three attempts. Windows also exposed unclosed SQLite connections during temporary-folder cleanup.

An early recording also exposed premature clarification while another selected source document was still unread. The final implementation uses strict structured responses, narrows action and invoice choices to the current eligible work, and directs the model to fetch available documents itself. It sends compact state and recent observations, classifies verified retry exhaustion in the host, and closes each database connection explicitly. The final measured run and integration checks are reported above. `model-evaluation-initial.json` preserves the initial results so this debugging evidence is reviewable.

## Submission checklist

- Source: `hasher-tanmay/autonomous-task-worker` on GitHub.
- Setup/run instructions, architecture, design decisions: README.
- Working demo: captioned `demo.mp4`, with model mode visible and real app outcomes.
- Criteria mapping and measured checks: this report and model result JSON.
- Limitations, assumptions, next steps and components: README.
- Personal interview guide: supplied privately to the owner, excluded from GitHub.
- Data: synthetic only. `.env`, runtime databases and run artifacts are ignored.
- Public live link: Gradio share was attempted but its relay timed out from the current network. Local setup and the recorded video are the reproducible demo.
