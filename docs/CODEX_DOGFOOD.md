# Codex Dogfood

Phase 4 dogfooding used `sago` on `sago` itself while shipping the Phase 3 real phase-gate feature.

## Feature Under Test

- Internal feature: structured phase reviews, real gate states, and blocked `next --json` behavior
- Repo used: this repository
- Builder assumption: Codex can rely on repo files plus CLI JSON only

## Control-Plane Loop Used

1. Read [docs/CONTROL_PLANE_ROADMAP.md](/Users/oha/sago/docs/CONTROL_PLANE_ROADMAP.md) and repo files instead of chat history.
2. Use `sago next --json` to pick the next actionable task.
3. Implement the task and run the task verify command.
4. Attach receipts with `sago checkpoint --receipt-file ... --json`.
5. Use `sago status --json` to inspect resume state, evidence, blockers, and phase gates.
6. When a phase completed, run `sago replan --feedback ... --yes` to force review before continuation.
7. Return to `sago next --json`.

## What Was Validated

- Failure handling: a failed receipt updates execution history and leaves a truthful resume point.
- Resume handling: `status --json` exposes the next task and next action without relying on prior chat.
- Evidence handling: receipt-backed verification changes `evidence_summary` deterministically.
- Review gating: finishing a phase blocks `next --json` with `phase_review_required` until review exists.
- Replan continuity: stored reviews survive replanning and unblock the next phase when approved.

## Mechanical Proof

- [tests/test_codex_flow.py](/Users/oha/sago/tests/test_codex_flow.py) exercises the Codex loop across failure, checkpoint, status, review, replan, and continuation.
- [docs/CODEX_WORKFLOW.md](/Users/oha/sago/docs/CODEX_WORKFLOW.md) is the executor runbook that matches the validated loop.

## Recorded Transcript

The following abridged transcript was captured from an actual local run of the Codex control-plane loop against a temporary `sago` project configured with a two-phase plan:

```text
$ sago next --json
{
  "state": "task",
  "task": "1.1",
  "phase": "Phase 1: Foundation"
}

$ sago checkpoint 1.1 --status failed --receipt-file ... --json
{
  "status": "failed",
  "receipt": {
    "attached": true,
    "receipt_id": "receipt-1.1-20260417T090000Z-fail",
    "path": ".planning/runtime/receipts/receipt-1.1-20260417T090000Z-fail.json"
  },
  "evidence_summary": {
    "receipts": 1,
    "verified_done": 0,
    "missing_done": 0,
    "repeated_failures": 0
  }
}

$ sago checkpoint 1.1 --status done --receipt-file ... --json
{
  "status": "done",
  "phase_completed": true,
  "receipt": {
    "attached": true,
    "receipt_id": "receipt-1.1-20260417T090500Z-pass",
    "path": ".planning/runtime/receipts/receipt-1.1-20260417T090500Z-pass.json"
  },
  "evidence_summary": {
    "receipts": 2,
    "verified_done": 1,
    "missing_done": 0,
    "repeated_failures": 0
  }
}

$ sago status --json
{
  "resume_point": {
    "last_completed": "1.1: Create config",
    "next_task": "2.1: Create main",
    "next_action": "Implement delivery task",
    "failure_reason": "None",
    "checkpoint": "sago-checkpoint-1.1"
  },
  "phase_gates": [
    {
      "phase_name": "Phase 1: Foundation",
      "status": "pending_review",
      "reviewed_at": null,
      "blocking_findings": [],
      "summary": ""
    }
  ]
}

$ sago replan --feedback "Continue with the approved foundation" --yes
Review: Phase 1: Foundation
Changes: +0 added, ~1 modified, -0 removed
Plan updated successfully!

$ sago next --json
{
  "state": "task",
  "task": "2.1",
  "phase": "Phase 2: Delivery"
}
```

## Conclusion

The current control plane is usable by Codex without hidden daemon state or dependence on prior conversation context. The critical requirements are the repo files, deterministic CLI JSON, and truthful checkpoint receipts.
