# Career-Ops Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Career-Ops job evaluation and resume customization into the auto-job-applier system to improve application quality and response rates through intelligent job scoring and selective resume tailoring.

**Architecture:** 
The integration is built in three independent tiers, each adding value without requiring the previous:
- **Tier 1 (Foundation):** Score jobs before applying; skip low-fit positions
- **Tier 2 (Quality):** Selectively customize resumes for top companies
- **Tier 3 (Automation):** Use Claude to generate fully customized applications

Each tier can run standalone and will be tested independently. Career-Ops runs as subprocess calls to Node.js scripts from the Python bot.

**Tech Stack:**
- Career-Ops (npm package `@santifer/career-ops`)
- Python (existing bot infrastructure)
- Subprocess for inter-process communication
- TDD for all features
- Existing LinkedIn/Naukri bots

**Spec:** This plan implements job evaluation and resume customization as described in the Career-Ops integration guide. The spec is the 3-tier strategy shown in the Architecture section above.

---

## Global Constraints

- Python 3.8+
- Node.js 16+ (for Career-Ops)
- Career-Ops workspace at `~/.gemini/antigravity/scratch/career-ops-workspace`
- All code must be testable with `pytest`
- Backward compatible with existing bot code
- No breaking changes to LinkedIn/Naukri bot interfaces
- All subprocess calls must have 30-second timeouts
- Resume customization only for jobs scoring >= 70%

---

## Review Focus

These are the failure modes most likely to bite a person using this software that the tasks' tests do not exercise:

1. **Career-Ops subprocess fails silently** — an error in the Node process returns empty JSON, and the bot applies with default score 50 instead of failing loudly
2. **Resume customization truncates content** — a long customized resume hits HTML length limit or loses critical sections
3. **Score threshold inconsistency** — different parts of the bot use different score cutoffs (70 vs 75 vs 80), leading to unpredictable apply/skip decisions
4. **Job description extraction fails on ATS portals** — some job sites wrap content in frames or lazy-load it, making extraction impossible; the bot should detect and skip
5. **Concurrent subprocess calls deadlock** — multiple jobs run customization in parallel and subprocess pipes fill up, blocking the bot

Each task adds a test for its failure mode to prove it doesn't ship.

---

## File Structure

```
auto-job-applier/
├── modules/
│   ├── career_ops_integration.py       [NEW] Tier 1: Job evaluation
│   ├── career_ops_customization.py     [NEW] Tier 2: Resume customization
│   ├── career_ops_automation.py        [NEW] Tier 3: Full Claude automation
│   └── (existing files unchanged)
├── tests/
│   └── test_career_ops_integration.py  [NEW] All tiers tested here
├── docs/
│   ├── CAREER_OPS_INTEGRATION.md       [NEW] User guide & workflow
│   └── superpowers/plans/
│       └── 2026-11-06-career-ops-integration.md [this file]
├── runAiBot.py                          [MODIFY] Add Tier 1 scoring loop
└── runNaukriBot.py                      [MODIFY] Add Tier 1 scoring loop
```

---

## Task 1: Tier 1 Foundation — Job Evaluation

> ## ✅ TIER 1 IS COMPLETE AND PROVEN LIVE (2026-11-17)
>
> **The implementation deliberately diverged from the names planned below — the names in
> this task are historical, the ones in this table are real:**
>
> | Planned here | What was actually built | Why |
> |---|---|---|
> | `modules/career_ops_integration.py` | `modules/career_ops.py` | Matches the repo's `modules/<topic>.py` convention |
> | `tests/test_career_ops_integration.py` | `tests/test_career_ops.py` | Follows the module name |
> | `evaluate_job(jd) -> {"score","decision","keywords"}` | `check_job_fit(jd) -> str \| None` (skip reason, or None to apply), over `score_job(...) -> JobScore` | A bot only needs "skip, and why"; returning the reason puts it straight into the log and the CSV |
> | `SCORE_THRESHOLD = 70` constant | `career_ops_min_score` setting, default `40` | Must be user-tunable; 70 skipped nearly everything in practice |
> | Score defaults to `50` on failure | `score = None`, and **an unscored job is never skipped** | A silent default of 50 is exactly the "fails silently" failure mode in Review Focus #1. `None` cannot be mistaken for a real score |
> | `jd-skill-gap.mjs` | `keyword-match.mjs` | The script Career-Ops actually ships |
>
> **Two behaviours added beyond the plan**, because a single default score hid real cases:
> a description naming fewer than 3 recognisable skills is applied to with `not enough to
> judge` (too little signal to skip on), and `career_ops_extra_skills` matches Power
> Platform/SharePoint terms Career-Ops' dictionary lacks, merged into the same score.
>
> **Proven live:** LinkedIn scored 16 jobs (43%–100%); Naukri scored a full run of 30
> applications and skipped a 25% Databricks/MLOps job with the reason recorded. Settings
> are editable in the control panel's **Job scoring** tab and documented in
> [`docs/config-settings.md`](../../config-settings.md).

**Files:**
- Create: ~~`modules/career_ops_integration.py`~~ → **built as `modules/career_ops.py`**
- Create: ~~`tests/test_career_ops_integration.py`~~ → **built as `tests/test_career_ops.py`** (17 tests)
- Modify: `runAiBot.py` (add scoring in job loop) → **done, `runAiBot.py:1541`**
- Modify: `runNaukriBot.py` (add scoring in job loop) → **done**

**Interfaces:**
- Consumes: Job description text from LinkedIn/Naukri, Career-Ops workspace path
- Produces: ~~`evaluate_job(job_description: str) -> dict`~~ → **`check_job_fit(description: str) -> str | None`**

---

### Task 1 Steps

- [x] **Step 1: Write test for job evaluation**

Create `tests/test_career_ops_integration.py`:

```python
import pytest
from modules.career_ops_integration import evaluate_job

def test_evaluate_job_returns_score_and_decision():
    """Score of > 70 returns 'apply', <= 70 returns 'skip'"""
    job_desc = """
    Senior Python Developer
    Requirements: 5+ years Python, AWS, Docker
    """
    result = evaluate_job(job_desc)
    assert "score" in result
    assert "decision" in result
    assert "keywords" in result
    assert result["decision"] in ["apply", "skip"]
    assert 0 <= result["score"] <= 100

def test_evaluate_job_returns_apply_for_high_match():
    """Job with 90%+ skill match returns 'apply'"""
    high_match_job = """
    Python Data Engineer
    Requirements: Python, pandas, SQL, AWS
    """
    result = evaluate_job(high_match_job)
    if result["score"] >= 70:
        assert result["decision"] == "apply"

def test_evaluate_job_returns_skip_for_low_match():
    """Job with < 30% skill match returns 'skip'"""
    low_match_job = """
    Rust Systems Programmer
    Requirements: Rust, WASM, C++
    """
    result = evaluate_job(low_match_job)
    if result["score"] < 70:
        assert result["decision"] == "skip"

def test_evaluate_job_subprocess_timeout():
    """If Career-Ops subprocess times out, return default score 50"""
    import subprocess
    original_run = subprocess.run
    
    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", timeout=30)
    
    subprocess.run = timeout_run
    try:
        result = evaluate_job("test job")
        assert result["score"] == 50
        assert result["decision"] == "apply"
    finally:
        subprocess.run = original_run
```

Run: `pytest tests/test_career_ops_integration.py::test_evaluate_job_returns_score_and_decision -v`
Expected: FAIL — module not found

- [x] **Step 2: Implement `evaluate_job()` in `modules/career_ops_integration.py`**
      → implemented as `score_job()` / `check_job_fit()` in `modules/career_ops.py`; the
      code block below is the original sketch, not what shipped.

Create `modules/career_ops_integration.py`:

```python
import subprocess
import json
import os
from pathlib import Path

CAREER_OPS_WORKSPACE = Path.home() / ".gemini" / "antigravity" / "scratch" / "career-ops-workspace"
SCORE_THRESHOLD = 70
SUBPROCESS_TIMEOUT = 30

def evaluate_job(job_description: str) -> dict:
    """
    Score a job description using Career-Ops.
    
    Args:
        job_description: Full text of the job posting
        
    Returns:
        {
            "score": int (0-100),
            "decision": "apply" | "skip",
            "keywords": list of extracted skill keywords
        }
    """
    try:
        result = subprocess.run(
            ["node", str(CAREER_OPS_WORKSPACE / "jd-skill-gap.mjs")],
            input=job_description,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        
        if result.returncode != 0:
            return _default_score()
        
        data = json.loads(result.stdout)
        score = data.get("match_percentage", 50)
        
        return {
            "score": score,
            "decision": "apply" if score >= SCORE_THRESHOLD else "skip",
            "keywords": data.get("keywords", [])
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return _default_score()

def _default_score() -> dict:
    """Safe default when Career-Ops unavailable"""
    return {
        "score": 50,
        "decision": "apply",
        "keywords": []
    }
```

- [x] **Step 3: Run test to verify it passes** — `tests/test_career_ops.py`, 17 tests passing
      (covers Node missing, workspace missing, CV missing, timeout, unreadable output,
      temp-file cleanup, threshold edges, and a real end-to-end Career-Ops run).

Run: `pytest tests/test_career_ops_integration.py::test_evaluate_job_returns_score_and_decision -v`
Expected: PASS

Run all: `pytest tests/test_career_ops_integration.py -v`
Expected: All 4 tests PASS

- [x] **Step 4: Update LinkedIn bot to use scoring** — `runAiBot.py:1541`, skipped jobs go to
      the failed-applications CSV with reason "Low Career-Ops match".

Modify `runAiBot.py` in the job application loop (find the section that applies jobs):

```python
from modules.career_ops_integration import evaluate_job

# In the job loop (find "for job in jobs:" or similar):
for job in search_results:
    eval_result = evaluate_job(job['description'])
    
    if eval_result['decision'] == 'skip':
        logger.info(f"Skipped {job['title']} (score: {eval_result['score']})")
        continue
    
    # Existing apply logic continues
    apply_to_job(job)
    logger.info(f"Applied to {job['title']} (score: {eval_result['score']})")
```

- [x] **Step 5: Update Naukri bot to use scoring**

Modify `runNaukriBot.py` the same way as LinkedIn bot above.

- [x] **Step 6: Run full test suite to ensure no regression** — 327 passed, 1 skipped
      (the skip needs `OPENAI_API_KEY`). Green in sequential and random ordering.

- [x] **Step 7: Manual test — apply to 5 jobs with scoring** — exceeded: a full live Naukri
      run of **30 applications** plus 16 scored LinkedIn jobs. Observed live:

```
Career-Ops match: 83% (10/12 skills), missing: Java, NLP      -> Applied
Career-Ops match: 100% (7/7 skills)                            -> Applied
Career-Ops match: 25% (1/4 skills), missing: Databricks, MLOps, NLP
-> Skipped - Career-Ops match 25% is below 40%
Career-Ops: only 2 recognised skill(s) in the description - not enough to judge, applying anyway.
```

- [x] **Step 8: Commit Tier 1**

```bash
git add modules/career_ops_integration.py tests/test_career_ops_integration.py runAiBot.py runNaukriBot.py
git commit -m "feat(tier-1): add job evaluation with Career-Ops scoring

- evaluate_job() scores jobs 0-100 based on skill match
- Bots skip jobs scoring < 70%
- Subprocess timeout defaults to safe score 50
- Tested on LinkedIn and Naukri bots

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

Shipped as `15ab3bf` "Score jobs with Career-Ops before applying; harden the Naukri bot".

### Steps the plan missed, needed before Tier 1 was actually usable

- [x] **Step 9: Expose the settings in the control panel** — the plan had the threshold as a
      Python constant, so there was no way to change it from the UI. Added a **Job scoring**
      tab (`config_schema.py`) with all five `career_ops_*` settings, and two tests in
      `tests/test_app_integration.py` covering that the tab is offered and that values
      coerce and round-trip into `user_config.json`.

- [x] **Step 10: Document it for the user** — Tier 1 shipped with no user-facing docs. Added a
      "Job scoring" section to `docs/config-settings.md`: the five settings, Node/Career-Ops
      setup, what the log output means, and the two "can't judge" cases (too few skills,
      scorer broken) with the reason nothing is ever skipped unscored.

### Tier 1 known limitation

Scoring is **keyword overlap, not comprehension**. A job wanting "5 years of Python" and a
resume saying "Python" score as a match; synonyms the dictionary lacks score as a miss
unless added to `career_ops_extra_skills`. The threshold is a coarse filter for obviously
wrong roles, not a judgement of fit — which is why the default is a permissive 40% and
unscorable jobs are applied to.

---

## Task 2: Tier 2 Quality — Selective Resume Customization

**Files:**
- Create: `modules/career_ops_customization.py`
- Modify: `tests/test_career_ops_integration.py` (add customization tests)
- Create: `docs/CAREER_OPS_INTEGRATION.md` (teaching guide)

**Interfaces:**
- Consumes: `evaluate_job()` from Task 1, base resume text, job title/company
- Produces: `customize_resume_for_job(job_description: str, base_resume: str, job_company: str) -> str` returns customized resume text

---

### Task 2 Steps

- [ ] **Step 1: Write test for resume customization**

Add to `tests/test_career_ops_integration.py`:

```python
from modules.career_ops_customization import customize_resume_for_job

def test_customize_resume_for_top_company():
    """Resume is customized for top-tier companies"""
    job_desc = "Senior Python Engineer at Google"
    base_resume = "5 years Python experience, AWS, Docker"
    
    customized = customize_resume_for_job(job_desc, base_resume, "Google")
    assert len(customized) > 0
    assert customized != base_resume  # Should be different

def test_customize_resume_maintains_content():
    """Customized resume doesn't lose critical content"""
    job_desc = "Data Scientist with Python, ML, SQL"
    base_resume = "PhD Machine Learning\n10 years experience\nSkills: Python, TensorFlow, SQL"
    
    customized = customize_resume_for_job(job_desc, base_resume, "Top Company")
    
    # Check critical keywords still present
    assert "Machine Learning" in customized or "ML" in customized
    assert "Python" in customized
    assert "SQL" in customized
```

Run: `pytest tests/test_career_ops_integration.py::test_customize_resume_for_top_company -v`
Expected: FAIL — function not defined

- [ ] **Step 2: Implement `customize_resume_for_job()` in `modules/career_ops_customization.py`**

Create `modules/career_ops_customization.py`:

```python
import subprocess
import json
import os
from pathlib import Path

CAREER_OPS_WORKSPACE = Path.home() / ".gemini" / "antigravity" / "scratch" / "career-ops-workspace"
SUBPROCESS_TIMEOUT = 30

TOP_COMPANIES = {
    "Google", "Microsoft", "Amazon", "Apple", "Meta",
    "Netflix", "Stripe", "Figma", "Datadog", "Notion",
    "GitHub", "GitLab", "Vercel", "Anthropic", "OpenAI"
}

def customize_resume_for_job(
    job_description: str, 
    base_resume: str, 
    job_company: str
) -> str:
    """
    Customize resume for a specific job using Career-Ops.
    
    Only customizes for top companies or if explicitly requested.
    Otherwise returns base resume unchanged.
    
    Args:
        job_description: Full job posting text
        base_resume: Base resume text
        job_company: Company name
        
    Returns:
        Customized resume text (or base if not customized)
    """
    if job_company not in TOP_COMPANIES:
        return base_resume
    
    try:
        result = subprocess.run(
            ["node", str(CAREER_OPS_WORKSPACE / "build-cv-html.mjs")],
            input=json.dumps({
                "jd": job_description,
                "resume": base_resume
            }),
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        
        if result.returncode == 0:
            customized = result.stdout.strip()
            if customized and len(customized) > 20:
                return customized
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    
    return base_resume

def should_customize(job_company: str) -> bool:
    """Check if a company warrants resume customization"""
    return job_company in TOP_COMPANIES
```

- [ ] **Step 3: Run customization tests**

Run: `pytest tests/test_career_ops_integration.py::test_customize_resume_for_top_company -v`
Expected: PASS

Run: `pytest tests/test_career_ops_integration.py::test_customize_resume_maintains_content -v`
Expected: PASS

- [ ] **Step 4: Update LinkedIn bot to use Tier 2**

Modify `runAiBot.py` in job loop:

```python
from modules.career_ops_integration import evaluate_job
from modules.career_ops_customization import customize_resume_for_job, should_customize

for job in search_results:
    eval_result = evaluate_job(job['description'])
    
    if eval_result['decision'] == 'skip':
        logger.info(f"Skipped {job['title']} (score: {eval_result['score']})")
        continue
    
    # TIER 2: Selective customization
    resume_to_use = base_resume
    if should_customize(job['company']):
        resume_to_use = customize_resume_for_job(
            job['description'],
            base_resume,
            job['company']
        )
        logger.info(f"✨ Customized resume for {job['company']}")
    
    apply_to_job(job, resume=resume_to_use)
    logger.info(f"Applied to {job['title']} (score: {eval_result['score']})")
```

- [ ] **Step 5: Write teaching documentation**

Create `docs/CAREER_OPS_INTEGRATION.md`:

```markdown
# Career-Ops Integration Guide

## How It Works

Your auto-job-applier now uses Career-Ops to:
1. **Score every job** (0-100) based on skill match
2. **Decide to apply or skip** (threshold: 70%)
3. **Customize resume** for top companies

## The Three Tiers

### Tier 1: Job Evaluation (Live Now)
- Scores every job before applying
- Skips jobs scoring < 70%
- Time: +5 sec/job
- Benefit: Better quality applications

### Tier 2: Resume Customization (Live Now)
- Tailors resumes for top 15 companies
- Generic resumes for other jobs (stays fast)
- Time: 3 sec avg (7 sec top companies, 1 sec others)
- Benefit: 3-5x better response rate for top companies

### Tier 3: Full Automation (Coming)
- Claude generates cover letters
- Claude drafts screening answers
- Claude fully customizes each application
- Time: 15 sec/job
- Benefit: Professional materials for every job

## Workflow: How to Apply

1. **Bot finds a job** on LinkedIn/Naukri
2. **Career-Ops scores it** (calls jd-skill-gap.mjs)
3. **If score < 70%:** Skip to next job
4. **If score >= 70%:** Check company
   - If in TOP_COMPANIES: Customize resume (7 sec)
   - Otherwise: Use generic resume (1 sec)
5. **Apply with resume**
6. **Log the score and decision**

## Top Companies (Auto-Customized)

Google, Microsoft, Amazon, Apple, Meta, Netflix, Stripe, Figma, Datadog, Notion, GitHub, GitLab, Vercel, Anthropic, OpenAI

Edit `modules/career_ops_customization.py` to add more.

## Troubleshooting

### Career-Ops not found
\`\`\`bash
career-ops init ~/.gemini/antigravity/scratch/career-ops-workspace
npm install -g @santifer/career-ops
\`\`\`

### Scores always 50?
Career-Ops subprocess timed out. Check logs for "subprocess timeout" error.

### Resume not customizing?
- Company not in TOP_COMPANIES list
- Job description too short
- Career-Ops returned error (check logs)

## Configuration

### Change score threshold:
File: `modules/career_ops_integration.py`
Line: `SCORE_THRESHOLD = 70`

### Add more top companies:
File: `modules/career_ops_customization.py`
Line: Edit `TOP_COMPANIES` set

### Timeout adjustment:
File: Both modules
Line: `SUBPROCESS_TIMEOUT = 30`
```

- [ ] **Step 6: Run full integration test**

Run: `pytest tests/test_career_ops_integration.py -v`
Expected: All tests pass (5+ tests now)

- [ ] **Step 7: Manual test — apply to 10 jobs, mix of top/other companies**

Run LinkedIn bot for 1 minute:
Expected: Logs show scores, customization messages for Google/Meta/etc, generic for others

- [ ] **Step 8: Commit Tier 2**

```bash
git add modules/career_ops_customization.py tests/test_career_ops_integration.py runAiBot.py docs/CAREER_OPS_INTEGRATION.md
git commit -m "feat(tier-2): add selective resume customization for top companies

- customize_resume_for_job() tailors for top 15 companies
- Generic resume used for other jobs to maintain speed
- Integrated into LinkedIn and Naukri bots
- Teaching documentation included

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Tier 3 Automation — Full Claude Integration (Future)

**Note:** This task is documented for future implementation. It requires Claude API integration which can be added later without breaking Tier 1 or 2.

**Files:**
- Create: `modules/career_ops_automation.py`
- Modify: `tests/test_career_ops_integration.py` (add automation tests)

**Interfaces:**
- Consumes: `evaluate_job()` from Task 1, customized resume from Task 2, Claude API client
- Produces: `generate_full_application(job_posting: str, resume: str, screening_questions: list) -> dict` returns `{"resume": str, "cover_letter": str, "screening_answers": dict}`

**Future Steps (not implemented yet):**
1. Use Claude to generate personalized cover letters
2. Use Claude to draft screening question answers
3. Combine all materials into one application
4. Expected time: 15 sec/job
5. Expected benefit: Professional materials for all applications

---

## Self-Review

> **Status as of 2026-11-17:** Tier 1 is **built, tested, documented and proven live**.
> Tier 2 (resume customization) and Tier 3 (full Claude automation) are **not started** —
> everything in Task 2 and Task 3 below is still a plan, not a description of the code.

**Spec Coverage:**
- ✅ Tier 1 evaluation: Task 1 covers job scoring
- ✅ Tier 2 customization: Task 2 covers selective resume tailoring
- ✅ Tier 3 automation: Task 3 documented for future
- ✅ Teaching: Task 2 includes full workflow documentation
- ✅ Integration: Tasks 1 & 2 modify both bots

**Step Scan:**
- All steps are executable from their descriptions
- Test code is provided (copy-paste ready)
- Implementation signatures are exact
- Commit steps are clear

**Type Consistency:**
- `evaluate_job()` returns consistent dict structure across all uses
- `customize_resume_for_job()` signature matches consumers
- Score threshold is consistent (70%) throughout

**Review Focus Tests (Tier 1, as actually shipped):**
- ✅ Review Focus #1 "fails silently" — fixed better than planned: a failed scorer returns
  `score=None` and logs a warning once, instead of a default 50 that reads like a real score
  (`test_node_not_installed`, `test_workspace_missing`, `test_cv_missing`, `test_timeout`,
  `test_garbage_output`)
- ✅ Review Focus #3 score-threshold consistency — one setting, `career_ops_min_score`,
  read in one place (`test_skip_reason_below_threshold`, `test_no_skip_at_threshold`)
- ✅ Review Focus #4 description extraction fails — an empty/"Unknown" description gives no
  score and the job is applied to, never skipped (`test_no_description_gives_no_score`)
- ✅ Review Focus #5 subprocess deadlock — `subprocess.run` with a 30s timeout, one call at a
  time, temp JD file always deleted (`test_temp_jd_file_is_removed`)
- ⬜ Review Focus #2 resume truncation — Tier 2 only, nothing to test yet

**Original plan's review notes (kept for the record):**
- ✅ Subprocess failure handled with default score (Task 1, Step 1)
- ✅ Resume content preservation tested (Task 2, Step 1)
- ✅ Score threshold consistency guaranteed by constants (both tasks)
- ⚠️ ATS portal detection: Not implemented; defaulting to apply is safe fallback
- ⚠️ Concurrent subprocess calls: Safe due to Python subprocess isolation

**Proportion:**
- 3 tasks, ~500 lines total implementation + tests
- Plan is focused on implementation, not transcript

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-06-career-ops-integration.md`.

**Does the plan capture what you want, and which execution approach should we use?**

- **Inline execution** - I implement every task in this session, then one final review. Fastest; all review happens at the end.
- **Subagent-driven** - A fresh agent implements each task with review after each one. Most thorough; costs more context.

**I recommend **inline execution**, because the three tasks are independent (Tier 2 doesn't depend on Tier 1 internals) but tightly coupled (each modifies the same bot files), so per-task reviews would require redundant re-reads. The plan is complete and testable, so one final review catches integration issues.**
