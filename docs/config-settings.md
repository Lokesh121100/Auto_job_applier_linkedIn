# `config/settings.py` — how the bot runs

Behaviour of the tool itself, rather than what it says in an application. Mostly the
**Run settings** tab of the control panel.

## LinkedIn behaviour

| Setting | Default | What it does |
|---|---|---|
| `close_tabs` | `False` | Whether to close the tabs opened for external (non-Easy-Apply) applications. **If you set this to `False`, close all tabs before closing the browser.** |
| `follow_companies` | `False` | Follow a company when submitting an Easy Apply application to it |

## Continuous running (beta)

| Setting | Default | What it does |
|---|---|---|
| `run_non_stop` | `False` | Keep running until you stop it. **Treated as `False` when `run_in_background = True`** |
| `alternate_sortby` | `True` | Alternate the "sort by" filter between runs |
| `cycle_date_posted` | `True` | Cycle through the "date posted" filter between runs |
| `stop_date_cycle_at_24hr` | `True` | Stop that cycle at "Past 24 hours" rather than going wider |

## Files and logs

| Setting | What it is |
|---|---|
| `file_name` | Where the applied-jobs history CSV is written, e.g. `"all excels/all_applied_applications_history.csv"`. Everything after the last `/` is the filename |
| `failed_file_name` | Same, for failed applications |
| `logs_folder_path` | Where run logs go, e.g. `"logs/"` |
| `log_level` | How much detail is written to `logs/log.txt` and printed while the tool runs: `"DEBUG"` for everything, `"INFO"` for the normal running commentary, `"WARNING"` for only what went wrong, `"ERROR"` for only crashes. Case-insensitive; anything unrecognised falls back to `"INFO"` |

## Run behaviour

| Setting | Default | What it does |
|---|---|---|
| `click_gap` | `1` | Maximum seconds to wait between clicks. Non-negative whole numbers only |
| `run_in_background` | `False` | Hide the Chrome window. May reduce performance. **Turning this on forces `pause_before_submit`, `pause_at_failed_question` and `run_non_stop` to `False`** — the safety pauses cannot work with no window to look at |
| `disable_extensions` | `False` | Disable browser extensions. Better for performance |
| `safe_mode` | `True` | Open Chrome in a clean **guest profile**. Turn this on if Chrome takes too long to open, or if you have several browser profiles |
| `smooth_scroll` | `False` | Smooth rather than instantaneous scrolling. Can reduce performance |
| `keep_screen_awake` | `True` | Keep the screen active and stop the machine sleeping. Temporarily deactivates while a dialog box is up (pause before submit, help needed on a question). The alternative is to set your OS sleep settings to Never |
| `auto_manage_driver` | `True` | Download and match the right Chrome driver automatically. If `False`, install a matching ChromeDriver yourself — see [install step 5](install.md#manual-install) |
| `showAiErrorAlerts` | `False` | Alert on errors from the AI API connection |

## Job scoring: skip jobs that don't match your resume

The **Job scoring** tab of the control panel. Before applying, the bot reads the job
description, counts how many of the skills it names also appear in your resume, and skips
the job when that percentage is too low. Works for both LinkedIn and Naukri.

| Setting | Default | What it does |
|---|---|---|
| `career_ops_scoring` | `True` | Turn scoring on or off. When off, every job is applied to as before |
| `career_ops_min_score` | `40` | Lowest match percentage that still gets an application. `0` to `100` |
| `career_ops_cv_path` | `"all resumes/default/resume.md"` | Your resume as **plain text or Markdown** — the scorer cannot read PDFs |
| `career_ops_extra_skills` | Power Platform / SharePoint terms | Skills the scorer's built-in list doesn't know. Matched ignoring case and spaces, so `PowerApps` matches `Power Apps` |
| `career_ops_path` | `""` | Folder where Career-Ops was installed. Empty means `~/.gemini/antigravity/scratch/career-ops-workspace` |

### Setting it up

Scoring is done by [Career-Ops](https://github.com/career-ops-hq/career-ops)' `keyword-match.mjs`,
run as a separate Node process. Nothing from Career-Ops is copied into this project.

1. Install [Node.js](https://nodejs.org) 16 or newer.
2. Create the workspace: `npx @santifer/career-ops init`
3. Save your resume as plain text or Markdown at `career_ops_cv_path`.

### What you see while it runs

```
Career-Ops match: 83% (10/12 skills), missing: Java, NLP
Career-Ops match: 25% (1/4 skills), missing: Databricks, MLOps, NLP
-> Skipped - Career-Ops match 25% is below 40% (missing: Databricks, MLOps, NLP)
```

Skipped jobs are recorded in the failed-applications CSV with the reason, so you can see
what was passed over and lower the threshold if it was too strict.

### When it can't judge a job

**Nothing is ever skipped without a score.** Three cases to know about:

- **The description names fewer than three recognisable skills** — too little to judge, so
  the job is applied to and the log says `not enough to judge, applying anyway`.
- **The description is shorter than 200 characters** — Career-Ops refuses to score it at
  all, which reaches the bot as zero recognised skills and the same
  `not enough to judge, applying anyway`. Real postings are comfortably longer; what lands
  here are "apply on our website" stubs and pages that load their text after the bot has
  read them.
- **Scoring is broken** — Node missing, no Career-Ops folder, no resume file at
  `career_ops_cv_path`, or the scorer timed out (30s). You get one warning in the log and
  the run continues applying to everything.

This is deliberate: a broken scorer must not quietly stop you applying to jobs. If every
job reports "applying anyway", check the log for that warning rather than assuming your
threshold is wrong.

### If your resume is a PDF

Export it to Markdown or plain text and point `career_ops_cv_path` at that file. Keep it
updated — the scorer compares against this file, not your real resume, so a stale copy
gives misleading scores and skips jobs you are qualified for.

## Dry runs: `stop_before_submit`

| Setting | Default | What it does |
|---|---|---|
| `stop_before_submit` | `False` | Fill in **every** application and stop at the Review step **without submitting** |

Useful for testing the tool, or for checking what it would answer before you trust it with
a real application. Each application is filled in completely, reaches the Review screen,
and is then discarded.

Two things worth knowing:

- A `stop_before_submit` stop is **not** counted as a failure. It is counted as a skip, so a
  clean dry run reads as skipped rather than as an all-failed run.
- It takes priority over `pause_before_submit` — the application is discarded before the
  confirmation dialog would appear.

`stop_before_submit` is only settable by editing `config/settings.py`; it has no field in
the control panel.

## In development

| Setting | Status |
|---|---|
| `generated_resume_path` | Folder for generated resumes. Part of the **experimental, in-development** resume generator |
| `connect_hr`, `connect_request_message` | Commented out in the file. Would send connection requests to recruiters with an optional personalised message (LinkedIn allows only 10 personalised invitations a month without Premium) |

---

[← Back to docs index](README.md) · [Configuration overview](configuration.md)
