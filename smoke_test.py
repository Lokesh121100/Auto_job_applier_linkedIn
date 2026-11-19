'''
Pre-run smoke test: checks everything a LinkedIn run depends on WITHOUT opening a browser or
touching LinkedIn, so a missing resume, a broken scorer or a bad setting is caught here instead
of costing a login.

    python smoke_test.py

Exit code 0 means ready to run. Anything marked FAIL would break or silently weaken a run;
WARN is worth knowing but does not stop one. Writes nothing.

License: MIT  (https://opensource.org/license/mit)
'''

import os
import sys
import csv
import shutil
import urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

results: list[tuple[str, str, str]] = []


def check(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))


print("\nSmoke test: LinkedIn run readiness\n")

# 1. Every setting validates, exactly as the bot does it at startup.
try:
    from modules.validator import validate_config
    validate_config()
    check("PASS", "config validates")
except Exception as e:
    check("FAIL", "config validates", str(e).strip().splitlines()[0][:160])

import config.settings as settings
import config.questions as questions
import config.search as search
import config.secrets as secrets

# 2. Credentials and the resume that will be uploaded.
check("PASS" if secrets.username and secrets.password else "FAIL", "LinkedIn credentials set")
resume = questions.default_resume_path
check("PASS" if os.path.isfile(resume) else "FAIL", "resume to upload exists", resume)

# 3. Career-Ops: Node, the workspace, the plain-text resume, and a REAL score. The sample is long
# enough on purpose: Career-Ops refuses any description under 200 characters.
try:
    from modules.career_ops import score_job, DEFAULT_WORKSPACE
    workspace = settings.career_ops_path or str(DEFAULT_WORKSPACE)
    check("PASS" if shutil.which("node") else "FAIL", "Node.js on PATH")
    check("PASS" if os.path.isfile(os.path.join(workspace, "keyword-match.mjs")) else "FAIL",
          "Career-Ops keyword-match.mjs present", workspace)
    check("PASS" if os.path.isfile(settings.career_ops_cv_path) else "FAIL",
          "plain-text resume for scoring exists", settings.career_ops_cv_path)
    sample = ("Power Platform Developer. You will build Power Apps and Power Automate flows on "
              "Dataverse, integrate with SharePoint and Azure, and report in Power BI. Strong SQL "
              "and C# a plus. Experience with REST APIs, Azure DevOps and agile delivery expected. ") * 2
    scored = score_job(sample, cv_path=settings.career_ops_cv_path, workspace=workspace,
                       extra_skills=settings.career_ops_extra_skills)
    if scored.score is None:
        check("FAIL", "Career-Ops produces a real score", scored.note or "no score returned")
    else:
        check("PASS", "Career-Ops produces a real score", f"{scored.score}% on a sample posting")
except Exception as e:
    check("FAIL", "Career-Ops scoring", f"{type(e).__name__}: {e}"[:160])

# 4. What gets typed into salary and notice-period boxes on a real application.
for name in ("current_ctc", "desired_salary", "notice_period"):
    value = getattr(questions, name, None)
    check("PASS" if value not in (None, "") else "FAIL", f"{name} is set", repr(value))
check("PASS", "answer for a 'current and expected ctc' box",
      f'"{questions.current_ctc} / {questions.desired_salary}"')

# 5. The history file the bot appends to: it must exist with the columns it writes.
history = settings.file_name
needed = {"Job ID", "Title", "Company", "Date Applied", "Job Link", "External Job link"}
try:
    with open(history, encoding="utf-8") as f:
        header = set(next(csv.reader(f)))
    missing = needed - header
    check("PASS" if not missing else "FAIL", "applied-history columns", ", ".join(sorted(missing)) or history)
    check("PASS" if os.access(history, os.W_OK) else "FAIL", "applied-history is writable")
except FileNotFoundError:
    check("PASS", "applied-history", "not created yet; the first run creates it")
except Exception as e:
    check("FAIL", "applied-history readable", str(e)[:120])

# 6. What this run will actually do, so nothing surprises you on LinkedIn.
locations = getattr(search, "search_locations", None) or [search.search_location]
check("PASS", "search terms x locations", f"{len(search.search_terms)} terms x {len(locations)} locations")
referrals_on = settings.send_referrals_after_applying or settings.referral_mode
check("WARN" if referrals_on else "PASS", "referral requests",
      "ON - will message real people" if referrals_on else "off - this run only applies")
check("PASS", "experience filter", f"skips jobs wanting more than {search.current_experience} years")
check("PASS", "Career-Ops threshold",
      f"skips jobs matching below {settings.career_ops_min_score}%" if settings.career_ops_scoring
      else "scoring is OFF")

# 7. Is anything already running? Two bots on one account is how checkpoints happen.
try:
    with urllib.request.urlopen("http://127.0.0.1:5000/api/status", timeout=3) as r:
        body = r.read().decode().replace(" ", "")
    running = '"running":true' in body
    check("WARN" if running else "PASS", "control panel",
          "a bot is ALREADY RUNNING" if running else "reachable, idle")
except Exception:
    check("WARN", "control panel", "not running (start it with: python app.py)")

failed = [r for r in results if r[0] == "FAIL"]
warned = [r for r in results if r[0] == "WARN"]
print(f"\n{len(results) - len(failed) - len(warned)} passed, {len(warned)} warning(s), {len(failed)} failed")
print("READY" if not failed else "NOT READY - fix the FAIL lines above before running")
sys.exit(1 if failed else 0)
