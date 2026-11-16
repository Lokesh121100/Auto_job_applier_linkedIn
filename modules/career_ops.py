'''
Scores a job description against your resume with Career-Ops' keyword-match.mjs
(github.com/career-ops-hq/career-ops, MIT) so the bots can skip poor fits before applying.

keyword-match.mjs is called as a separate Node process - nothing from Career-Ops is
copied here. Its skill dictionary has no Power Platform / SharePoint terms, so
`career_ops_extra_skills` are matched here in Python and merged into the same score.

Any failure (no Node, no Career-Ops folder, no resume text, timeout) gives no score,
and an unscored job is never skipped: a broken scorer must not silently stop applying.

License: MIT  (https://opensource.org/license/mit)
'''

import os
import re
import json
import shutil
import tempfile
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import (career_ops_scoring, career_ops_min_score, career_ops_path,
                             career_ops_cv_path, career_ops_extra_skills)
from modules.helpers import print_lg, logger

DEFAULT_WORKSPACE = Path.home() / ".gemini" / "antigravity" / "scratch" / "career-ops-workspace"
NODE_TIMEOUT = 30
MIN_SKILLS_TO_JUDGE = 3


@dataclass
class JobScore:
    score: int | None                     # 0-100, or None when the job couldn't be scored
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    note: str = ""
    failed: bool = False                  # True when the scorer itself broke, not just a vague JD


def _key(skill: str) -> str:
    return re.sub(r"\s+", "", skill).lower()


def _mentions(text: str, skill: str) -> bool:
    words = r"\s*".join(re.escape(word) for word in skill.split())
    return re.search(rf"(?<!\w){words}(?!\w)", text, re.IGNORECASE) is not None


def _run_keyword_match(description: str, cv_path: str, workspace: str) -> tuple[list[str], list[str]] | JobScore:
    '''Career-Ops' (present, missing) keywords, or a failed JobScore saying why.'''
    node = shutil.which("node")
    if not node:
        return JobScore(None, note="Node.js not found on PATH", failed=True)
    script = os.path.join(workspace, "keyword-match.mjs")
    if not os.path.isfile(script):
        return JobScore(None, note=f"Career-Ops keyword-match.mjs not found in {workspace}", failed=True)
    if not os.path.isfile(cv_path):
        return JobScore(None, note=f"Resume text not found at {cv_path}", failed=True)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as jd_file:
        jd_file.write(description)
    try:
        result = subprocess.run([node, script, "--jd-text", jd_file.name, "--cv", os.path.abspath(cv_path), "--json"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=NODE_TIMEOUT, cwd=workspace)
    except subprocess.TimeoutExpired:
        return JobScore(None, note=f"Career-Ops timed out after {NODE_TIMEOUT}s", failed=True)
    except OSError as e:
        return JobScore(None, note=f"Could not start Career-Ops: {e}", failed=True)
    finally:
        os.unlink(jd_file.name)

    # Exit 1 is keyword-match.mjs refusing a JD with no skills it knows - not an error here,
    # the extra skills may still find some.
    if result.returncode != 0:
        logger.debug("keyword-match.mjs exited %s: %s", result.returncode, result.stderr.strip())
        return [], []
    try:
        data = json.loads(result.stdout)
        return list(data.get("present", [])), list(data.get("missing", []))
    except (json.JSONDecodeError, AttributeError):
        return JobScore(None, note="Career-Ops gave unreadable output", failed=True)


def score_job(description: str, *, cv_path: str, workspace: str, extra_skills: list[str]) -> JobScore:
    if not description or not description.strip() or description == "Unknown":
        return JobScore(None, note="no job description")

    found = _run_keyword_match(description, cv_path, workspace)
    if isinstance(found, JobScore):
        return found
    present, missing = found

    seen = {_key(skill) for skill in present + missing}
    with open(cv_path, encoding="utf-8", errors="replace") as f:
        cv_text = f.read()
    for skill in extra_skills:
        if _key(skill) in seen or not _mentions(description, skill): continue
        seen.add(_key(skill))
        (present if _mentions(cv_text, skill) else missing).append(skill)

    total = len(present) + len(missing)
    if total < MIN_SKILLS_TO_JUDGE:
        return JobScore(None, present, missing, note=f"only {total} recognised skill(s) in the description - not enough to judge")
    return JobScore(round(len(present) * 100 / total), present, missing)


def skip_reason(result: JobScore, min_score: int) -> str | None:
    if result.score is None or result.score >= min_score:
        return None
    return f"Career-Ops match {result.score}% is below {min_score}% (missing: {', '.join(result.missing)})"


_warned: set[str] = set()


def check_job_fit(description: str) -> str | None:
    '''Scores the job and prints the result. Returns why to skip it, or None to go ahead and apply.'''
    if not career_ops_scoring:
        return None
    result = score_job(description, cv_path=career_ops_cv_path, workspace=career_ops_path or str(DEFAULT_WORKSPACE),
                       extra_skills=career_ops_extra_skills)
    if result.score is None:
        if result.failed and result.note not in _warned:
            _warned.add(result.note)
            logger.warning("Career-Ops scoring isn't working (%s) - applying without it.", result.note)
        elif not result.failed:
            print_lg(f"Career-Ops: {result.note}, applying anyway.")
        return None
    print_lg(f"Career-Ops match: {result.score}% ({len(result.present)}/{len(result.present) + len(result.missing)} skills)"
             + (f", missing: {', '.join(result.missing)}" if result.missing else ""))
    return skip_reason(result, career_ops_min_score)
