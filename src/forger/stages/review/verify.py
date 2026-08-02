"""Verify review stage: multi-reviewer consensus logic."""

import re
from pathlib import Path

from forger.config import ProjectConfig
from forger.stages import check_stage_guards
from forger.state import save_change


def _extract_verdict(content: str) -> str | None:
    match = re.search(
        r"\*\*Verdict:\s*(accepted|warned|changes_requested)\*\*",
        content,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def _apply_consensus(verdicts: dict[str, str], consensus: str) -> str:
    statuses = list(verdicts.values())
    if consensus == "majority":
        accept_count = sum(1 for s in statuses if s in ("accepted", "warned"))
        if accept_count > len(statuses) / 2:
            return "warned" if any(s == "warned" for s in statuses) else "accepted"
        return "changes_requested"
    # "all" (default): every reviewer must accept/warn
    if all(s in ("accepted", "warned") for s in statuses):
        return "warned" if any(s == "warned" for s in statuses) else "accepted"
    return "changes_requested"


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    guards = check_stage_guards(run_dir, "fixed")
    if guards is None:
        return False
    state, body = guards
    change_path = run_dir / "change.md"

    reviews_dir = run_dir / "reviews"
    if not reviews_dir.exists():
        return False

    feedback_files = sorted(reviews_dir.glob("review-*-feedback.md"))
    current_round = len(feedback_files) + 1

    reviewers = config.review.reviewers
    verdicts = {}
    for reviewer in reviewers:
        review_file = reviews_dir / f"review-{current_round}-{reviewer.role}.md"
        if not review_file.exists():
            print(
                f"  [review/verify] missing: {review_file.name} — {reviewer.role} reviewer produced no output",
                flush=True,
            )
            return False
        content = review_file.read_text()
        verdict = _extract_verdict(content)
        if not verdict:
            print(
                f"  [review/verify] no verdict line in {review_file.name} — expected **Verdict: accepted|warned|changes_requested**",
                flush=True,
            )
        verdicts[reviewer.role] = verdict or "changes_requested"

    final_verdict = _apply_consensus(verdicts, config.review.consensus)

    if final_verdict in ("accepted", "warned"):
        state.pipeline.stage = "reviewed"
        save_change(change_path, state, body)
        return True

    # Changes requested — check loop limit
    if current_round >= config.review.max_loops:
        state.pipeline.parked_reason = (
            f"Review loop exceeded ({current_round} attempts)"
        )
        save_change(change_path, state, body)
        return False

    # Write combined feedback file from reviewers that requested changes
    feedback_parts = [f"# Review Feedback Round {current_round}\n"]
    for reviewer in reviewers:
        if verdicts.get(reviewer.role) == "changes_requested":
            content = (
                reviews_dir / f"review-{current_round}-{reviewer.role}.md"
            ).read_text()
            feedback_parts.append(f"## From {reviewer.role} reviewer\n\n{content}\n")
    feedback_path = reviews_dir / f"review-{current_round}-feedback.md"
    feedback_path.write_text("\n".join(feedback_parts))

    state.pipeline.stage = "fix-chosen"
    save_change(change_path, state, body)
    return True
