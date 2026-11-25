'''
Tests for modules/career_ops.py: scoring a job description against the resume with
Career-Ops' keyword-match.mjs, plus extra skills Career-Ops' dictionary doesn't know.
The Node call is faked except in the one integration test, which runs only when Node
and a Career-Ops workspace are actually installed.

License: MIT  (https://opensource.org/license/mit)
'''

import json
import os
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from modules import career_ops


JD = "Requirements: Power Apps, Dataverse, Azure, React, TypeScript, Kubernetes, Terraform"


@pytest.fixture
def cv(tmp_path):
    path = tmp_path / "resume.md"
    path.write_text("Built PowerApps on Dataverse with Azure, React and TypeScript.", encoding="utf-8")
    return str(path)


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "career-ops"
    ws.mkdir()
    (ws / "keyword-match.mjs").write_text("// fake", encoding="utf-8")
    return str(ws)


def fake_node(monkeypatch, *, present=(), missing=(), returncode=0, stdout=None, raises=None):
    '''Replace the Node call. Returns the list of argv lists it was called with.'''
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if raises: raise raises
        out = stdout if stdout is not None else json.dumps({"present": list(present), "missing": list(missing)})
        return types.SimpleNamespace(returncode=returncode, stdout=out, stderr="")

    monkeypatch.setattr(career_ops.shutil, "which", lambda name: "node")
    monkeypatch.setattr(career_ops.subprocess, "run", run)
    return calls


EXTRA = ["Power Apps", "Dataverse", "SPFx"]


def score(description, cv, workspace):
    return career_ops.score_job(description, cv_path=cv, workspace=workspace, extra_skills=EXTRA)


# ------------------------------- scoring ---------------------------------------------
def test_merges_career_ops_keywords_with_extra_skills(monkeypatch, cv, workspace):
    fake_node(monkeypatch, present=["Azure", "React", "TypeScript"], missing=["Kubernetes", "Terraform"])
    result = score(JD, cv, workspace)
    # 5 from Career-Ops + Power Apps, Dataverse from the extra list (SPFx isn't in the JD).
    assert sorted(result.present) == ["Azure", "Dataverse", "Power Apps", "React", "TypeScript"]
    assert sorted(result.missing) == ["Kubernetes", "Terraform"]
    assert result.score == 71


def test_thin_description_career_ops_refuses_is_applied_to_not_skipped(monkeypatch, cv, workspace):
    '''keyword-match.mjs exits 1 on a description under 200 characters ("too thin to score").
    That must read as "cannot judge" - applied to - and never as a 0% match worth skipping,
    which would silently drop every job whose page hadn't finished loading.'''
    fake_node(monkeypatch, returncode=1, stdout="")
    result = score("Senior Rust Engineer. Rust, WASM, C++. Apply on our site.", cv, workspace)
    assert result.score is None
    assert not result.failed                            # a thin JD is not a broken scorer
    assert career_ops.skip_reason(result, 40) is None   # so the job is applied to


def test_extra_skill_in_jd_but_not_cv_is_missing(monkeypatch, cv, workspace):
    fake_node(monkeypatch, present=["Azure", "React"], missing=[])
    result = score("Need SPFx, Azure, React", cv, workspace)
    assert result.missing == ["SPFx"]
    assert result.score == 67


def test_extra_skill_matches_whole_words_only(monkeypatch, cv, workspace):
    fake_node(monkeypatch, present=["Azure", "React", "TypeScript"])
    result = score("Azure, React, TypeScript, SPFxtended tooling", cv, workspace)
    assert "SPFx" not in result.present + result.missing


def test_too_few_recognised_skills_gives_no_score(monkeypatch, cv, workspace):
    # keyword-match.mjs exits 1 when a JD names no skills it recognises.
    fake_node(monkeypatch, returncode=1, stdout="")
    result = score("Great team player wanted. Dataverse.", cv, workspace)
    assert result.score is None
    assert "not enough" in result.note


@pytest.mark.parametrize("description", ["", "   ", "Unknown"])
def test_no_description_gives_no_score(monkeypatch, cv, workspace, description):
    calls = fake_node(monkeypatch)
    result = score(description, cv, workspace)
    assert result.score is None
    assert calls == []


def test_temp_jd_file_is_removed(monkeypatch, cv, workspace):
    calls = fake_node(monkeypatch, present=["Azure", "React", "TypeScript"])
    score(JD, cv, workspace)
    jd_file = calls[0][calls[0].index("--jd-text") + 1]
    assert not os.path.exists(jd_file)


# ------------------------------- failures never crash, never skip ---------------------
def test_node_not_installed(monkeypatch, cv, workspace):
    monkeypatch.setattr(career_ops.shutil, "which", lambda name: None)
    result = score(JD, cv, workspace)
    assert result.score is None
    assert "Node" in result.note


def test_workspace_missing(monkeypatch, cv, tmp_path):
    fake_node(monkeypatch)
    result = score(JD, cv, str(tmp_path / "nowhere"))
    assert result.score is None
    assert "keyword-match.mjs" in result.note


def test_cv_missing(monkeypatch, workspace, tmp_path):
    fake_node(monkeypatch)
    result = score(JD, str(tmp_path / "no-cv.md"), workspace)
    assert result.score is None
    assert "resume" in result.note.lower()


def test_timeout(monkeypatch, cv, workspace):
    fake_node(monkeypatch, raises=subprocess.TimeoutExpired("node", 30))
    result = score(JD, cv, workspace)
    assert result.score is None
    assert "timed out" in result.note


def test_garbage_output(monkeypatch, cv, workspace):
    fake_node(monkeypatch, stdout="not json")
    result = score(JD, cv, workspace)
    assert result.score is None


# ------------------------------- skip decision ---------------------------------------
def test_skip_reason_below_threshold():
    reason = career_ops.skip_reason(career_ops.JobScore(30, ["A"], ["B", "C"]), min_score=40)
    assert reason is not None and "30%" in reason and "40%" in reason


def test_no_skip_at_threshold():
    assert career_ops.skip_reason(career_ops.JobScore(40, ["A"], ["B"]), min_score=40) is None


def test_no_skip_when_unscored():
    assert career_ops.skip_reason(career_ops.JobScore(None, [], [], "Node missing"), min_score=40) is None


def test_check_job_fit_off_does_nothing(monkeypatch):
    monkeypatch.setattr(career_ops, "career_ops_scoring", False)
    monkeypatch.setattr(career_ops, "score_job", lambda *a, **k: pytest.fail("scored while disabled"))
    assert career_ops.check_job_fit(JD) is None


def test_check_job_fit_returns_reason(monkeypatch):
    monkeypatch.setattr(career_ops, "career_ops_scoring", True)
    monkeypatch.setattr(career_ops, "career_ops_min_score", 50)
    monkeypatch.setattr(career_ops, "score_job", lambda *a, **k: career_ops.JobScore(20, ["A"], ["B", "C", "D", "E"]))
    assert "20%" in career_ops.check_job_fit(JD)


# ------------------------------- real Career-Ops -------------------------------------
REAL_WS = Path.home() / ".gemini" / "antigravity" / "scratch" / "career-ops-workspace"


@pytest.mark.skipif(not shutil.which("node") or not (REAL_WS / "keyword-match.mjs").exists(),
                    reason="Node and a Career-Ops workspace are needed for the real run")
def test_real_career_ops_run(cv):
    # keyword-match.mjs refuses JDs under 200 characters, so this one is realistic length.
    jd = ("We are hiring a Power Platform Developer to build business apps for our clients.\n"
          "Requirements:\n- 3+ years building Power Apps on Dataverse\n- Azure, React and TypeScript\n"
          "- Kubernetes and Terraform experience is a plus\n"
          "You will work with stakeholders to gather requirements and ship solutions.")
    result = career_ops.score_job(jd, cv_path=cv, workspace=str(REAL_WS), extra_skills=EXTRA)
    assert result.score is not None, result.note
    assert "Kubernetes" in result.missing
    assert "Power Apps" in result.present


# ------------- no skills found AND a title outside your field: skip -------------------
TITLE_WORDS = ["Developer", ".NET", "Power BI", "Data Analyst"]
NO_SKILLS = career_ops.JobScore(None, [], [], note="only 0 recognised skill(s) in the description - not enough to judge")


def test_zero_skills_and_an_off_field_title_is_skipped(monkeypatch):
    '''Seen live 2026-11-19: "Chartered Accountant" (accounting, MIS, Ind AS) was Easy Applied
    to because 0 recognised skills meant "not enough to judge, applying anyway".'''
    monkeypatch.setattr(career_ops, "career_ops_scoring", True)
    monkeypatch.setattr(career_ops, "score_job", lambda *a, **k: NO_SKILLS)
    reason = career_ops.check_job_fit(JD, title="Chartered Accountant", title_keywords=TITLE_WORDS)
    assert reason and "Chartered Accountant" in reason


def test_zero_skills_but_a_title_in_your_field_still_applies(monkeypatch):
    '''Some real matches score 0 too - UPS ".NET" postings open with ~2,000 characters of
    company boilerplate. The title is the evidence there, so they must not be skipped.'''
    monkeypatch.setattr(career_ops, "career_ops_scoring", True)
    monkeypatch.setattr(career_ops, "score_job", lambda *a, **k: NO_SKILLS)
    assert career_ops.check_job_fit(JD, title="Senior Application Developer - .NET", title_keywords=TITLE_WORDS) is None


def test_zero_skills_without_title_words_keeps_the_old_behaviour(monkeypatch):
    '''Naukri calls check_job_fit with the description only; nothing changes for it.'''
    monkeypatch.setattr(career_ops, "career_ops_scoring", True)
    monkeypatch.setattr(career_ops, "score_job", lambda *a, **k: NO_SKILLS)
    assert career_ops.check_job_fit(JD) is None
    assert career_ops.check_job_fit(JD, title="Chartered Accountant", title_keywords=[]) is None


def test_one_or_two_skills_is_still_not_enough_to_skip(monkeypatch):
    '''Only a description with NO recognised skill is evidence of the wrong field.'''
    monkeypatch.setattr(career_ops, "career_ops_scoring", True)
    monkeypatch.setattr(career_ops, "score_job", lambda *a, **k: career_ops.JobScore(None, ["SQL"], [], note="only 1"))
    assert career_ops.check_job_fit(JD, title="Business Intelligence Lead", title_keywords=TITLE_WORDS) is None
