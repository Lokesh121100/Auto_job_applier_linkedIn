# Experience answers on Easy Apply forms (short design)

**Why:** live run 2026-11-23 reached two ValGenesis Easy Apply forms; both were skipped on
questions the user can honestly answer: "Years of work experience in your chosen engineering
field" (dropdown of ranges) and "What area have you most experience in?" (checkbox group).
The user has **2 years**, and has worked with the technologies on the resume.

**Rule (user-approved):** answer from the resume only. A technology not in
`career_ops_cv_path` (`all resumes/default/resume.md`) is never claimed; that question stays
unanswered and the job goes to the needs-answer sheet, as today.

## Changes (all in `answer_questions`, `runAiBot.py`)

1. **Total experience, dropdown and radio** - a label that asks for total experience (the text
   branch's existing `total_experience_terms` rule, plus "in your (chosen) ... field / career /
   industry") answers `years_of_experience`. A numeric answer is matched as a range first
   ("Less than 2" / "2-4" / "2,4" / "12+"; half-open `[low, high)`), because the generic matcher
   would pick "Less than 2" for "2".
2. **Years with one technology, text box** - "years of experience with C#": if the label names a
   resume skill, answer `years_of_experience`; otherwise unchanged (left empty).
3. **"Which area do you have experience in?" checkbox group** (read by the radio branch) - tick
   every option whose words appear in the resume AND in the job description ("AI/ML" matches on
   either part). Nothing matched -> left unanswered, as today.

## Approaches considered
- **Resume-backed (picked):** honest, no AI, uses files that exist.
- Claim whatever the JD asks: rejected - false claims on real applications.
- AI answers (`use_AI`): off in config, slower, still needs the same honesty rule.

## Status (2026-11-25)
- **Built:** change 1 - a total-experience dropdown or radio picks the option holding `years_of_experience`
  (`asks_total_experience`, `years_option`), and the text box now also accepts "...in your chosen field".
- **Not built, on purpose:** change 2 (years with one technology). Answering the total for every skill on the
  resume can overstate it (Power BI is about 6 months of the 2 years), so it waits for a per-skill years table
  from the user. Change 3 (area checkboxes) would not unlock the ValGenesis forms: they also carry the
  unlabelled checkbox that is never ticked.
- Measured on the needs-answer sheet: this design alone fully unlocks about 5 of 49 blocked jobs; 33 are blocked
  only by company, legal or personal questions the bot must never guess.

## Not in scope
Tier 2 resume rewriting; search filter `current_experience = 3` (user's setting, left alone).
The unlabelled "Unknown" checkbox (8 jobs in the sheet) only gets its question text read, using
the dropdown branch's existing fallback, so the sheet says what it asks; it is still never ticked.
