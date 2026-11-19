'''
Regression tests for the runAiBot.py fixes. Selenium can't drive a real browser here,
so the browser session is stubbed out at import time and the DOM is faked with small
objects that answer find_element / find_elements.

Each test fails if the specific bug it covers comes back.

License: MIT  (https://opensource.org/license/mit)
'''

import inspect
import os
import sys
import types
from datetime import datetime, timedelta

import pytest
from selenium.common.exceptions import NoSuchElementException


@pytest.fixture(scope="module")
def bot():
    '''Import runAiBot with a stubbed browser session, so importing it never opens Chrome.'''
    fake_chrome = types.ModuleType("modules.open_chrome")
    fake_chrome.options = fake_chrome.driver = fake_chrome.actions = fake_chrome.wait = None
    sys.modules["modules.open_chrome"] = fake_chrome
    import runAiBot
    return runAiBot


class FakeElement:
    '''Stand-in for a WebElement: `children` maps an XPath/class to what it resolves to.'''

    def __init__(self, text="", value="", children=None):
        self.text = text
        self.value = value
        self.children = children or {}
        self.cleared = False

    def clear(self):
        self.cleared = True
        self.value = ""

    def send_keys(self, keys):
        self.value += str(keys)

    def get_attribute(self, name):
        return self.value if name == "value" else None

    def is_selected(self):
        return False

    def find_element(self, by, locator):
        if locator in self.children:
            return self.children[locator]
        raise NoSuchElementException(locator)

    def find_elements(self, by, locator):
        found = self.children.get(locator)
        if isinstance(found, list):
            return found
        return [found] if found else []


# --------------------------- A: the do_actions UnboundLocalError -------------------
def test_textarea_question_without_an_earlier_text_input(bot, monkeypatch):
    '''A cover-letter textarea used to read do_actions, which only the text branch set.'''
    typed = []
    monkeypatch.setattr(bot, "human_type", lambda target, text: typed.append((target, text)), raising=False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)

    textarea = FakeElement()
    question = FakeElement(children={
        ".//textarea": textarea,
        ".//label[@for]": FakeElement(text="Cover letter"),
    })
    modal = FakeElement(children={".//div[@data-test-form-element]": [question]})

    answered = bot.answer_questions(modal, set(), "Remote")   # used to raise UnboundLocalError

    assert len(answered) == 1
    assert textarea.cleared
    assert typed and typed[0][0] is textarea       # L: typed through human_type, not send_keys


def test_text_question_is_typed_through_human_type(bot, monkeypatch):
    typed = []
    monkeypatch.setattr(bot, "human_type", lambda target, text: typed.append((target, text)), raising=False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)

    text_input = FakeElement()
    question = FakeElement(children={
        ".//input[@type='text']": text_input,
        ".//label[@for]": FakeElement(text="First name"),
    })
    modal = FakeElement(children={".//div[@data-test-form-element]": [question]})

    bot.answer_questions(modal, set(), "Remote")

    assert typed == [(text_input, bot.first_name)]


# -------- the 2026 Easy Apply modal: questions must be FOUND before they can be answered --------
class AriaField(FakeElement):
    '''An <input type=text> whose question is its aria-label, as on LinkedIn's 2026 modal.'''

    def __init__(self, aria):
        super().__init__()
        self.aria = aria

    def get_attribute(self, name):
        return {"aria-label": self.aria, "value": self.value}.get(name)


ARIA_FIELD_XPATH = ".//*[(self::input or self::textarea) and @aria-label]"


def new_layout_question(question_text, aria=None):
    '''(wrapper, parent, field) for one question, shaped like the captured "Additional Questions"
    step: <div><p>Q*</p><div componentkey="easyApplyFieldFocus_..."><input aria-label="Q"></div></div>.
    The wrapper is the easyApplyFieldFocus_ div; its parent holds the <p>.'''
    field = AriaField(question_text.rstrip("*").strip() if aria is None else aria)
    parent = FakeElement(children={
        ".//input[@type='text']": field,
        ARIA_FIELD_XPATH: field,
        ".//p": FakeElement(text=question_text),
    })
    return FakeElement(children={"..": parent}), parent, field


def new_layout_modal(bot, *wrappers):
    return FakeElement(children={".//div[@data-test-form-element]": [],
                                 bot.NEW_LAYOUT_FIELD_XPATH: list(wrappers)})


def test_new_layout_questions_are_found_through_their_field_wrappers(bot):
    '''answer_questions() only looked for data-test-form-element, which the new modal does not
    have, so it saw no questions at all, answered nothing and stalled on "Invalid input".'''
    wrapper_a, parent_a, _ = new_layout_question("What is your notice period?*")
    wrapper_b, parent_b, _ = new_layout_question("What is your current and expected ctc ?*")
    assert bot.find_question_elements(new_layout_modal(bot, wrapper_a, wrapper_b)) == [parent_a, parent_b]


def test_two_fields_under_one_parent_are_one_question(bot):
    wrapper, parent, _ = new_layout_question("Preferred work mode?*")
    twin = FakeElement(children={"..": parent})
    assert bot.find_question_elements(new_layout_modal(bot, wrapper, twin)) == [parent]


def test_the_classic_layout_is_still_preferred_when_present(bot):
    classic = FakeElement()
    wrapper, _, _ = new_layout_question("Anything?*")
    modal = FakeElement(children={".//div[@data-test-form-element]": [classic],
                                  bot.NEW_LAYOUT_FIELD_XPATH: [wrapper]})
    assert bot.find_question_elements(modal) == [classic]


def test_new_layout_label_comes_from_the_field_without_its_asterisk(bot):
    _, parent, _ = new_layout_question("What is your notice period?*")
    assert bot.read_question_label(parent) == "What is your notice period?"


def test_new_layout_label_falls_back_to_the_paragraph(bot):
    parent = FakeElement(children={".//p": FakeElement(text="Do you have a laptop?*")})
    assert bot.read_question_label(parent) == "Do you have a laptop?"


def test_an_unreadable_label_is_unknown_not_empty(bot):
    assert bot.read_question_label(FakeElement()) == "Unknown"


def test_the_classic_label_is_read_exactly_as_before(bot):
    parent = FakeElement(children={".//label[@for]": FakeElement(text="First name")})
    assert bot.read_question_label(parent) == "First name"


@pytest.fixture
def money(bot, monkeypatch):
    '''Fixed figures, so these tests do not depend on the developer's own user_config.json.'''
    monkeypatch.setattr(bot, "current_ctc", "400000")
    monkeypatch.setattr(bot, "desired_salary", "800000")
    monkeypatch.setattr(bot, "notice_period", "15")


def answer_new_layout(bot, monkeypatch, *question_texts):
    typed = []
    monkeypatch.setattr(bot, "human_type", lambda target, text: typed.append(text), raising=False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    wrappers = [new_layout_question(t)[0] for t in question_texts]
    bot.answer_questions(new_layout_modal(bot, *wrappers), set(), "Chennai")
    return typed


def test_the_questions_that_stalled_a_real_application_are_now_seen_and_the_answerable_one_filled(bot, monkeypatch, money):
    '''Captured live at step 4 of 5: both boxes required and empty, and the bot looped on Review
    until it gave up because it never saw either. It now sees both: the notice period is answered,
    and the two-figure CTC box is deliberately left for the skip path (next test).'''
    bot.unanswered_questions.clear()
    typed = answer_new_layout(bot, monkeypatch,
                              "What is your current and expected ctc ?*",
                              "What is your notice period?*")
    assert typed == ["", "15"]


def test_a_current_and_expected_ctc_box_is_left_unanswered_not_guessed(bot, monkeypatch, money):
    '''Neither figure alone is a true answer, and sending both as "400000 / 800000" was rejected
    live with "Invalid input" (the box takes one number), which stalled the application. Leaving
    it empty gets the job skipped with the question named, and nothing doubtful reaches an employer.'''
    bot.unanswered_questions.clear()
    typed = answer_new_layout(bot, monkeypatch, "What is your current and expected ctc ?*")
    assert typed == [""]
    assert "What is your current and expected ctc ?" in bot.unanswered_questions


@pytest.mark.parametrize("question, expected", [
    ("What is your current ctc?*", "400000"),
    ("What is your expected salary?*", "800000"),
    ("What is your present compensation?*", "400000"),
    ("What is your desired salary?*", "800000"),
])
def test_a_single_figure_ctc_question_still_gets_a_single_figure(bot, monkeypatch, money, question, expected):
    assert answer_new_layout(bot, monkeypatch, question) == [expected]


def test_a_question_with_no_configured_answer_is_left_empty_not_guessed(bot, monkeypatch, money):
    '''The stall guard then skips the job, which is right: a guess goes to a real employer.'''
    bot.unanswered_questions.clear()
    answer_new_layout(bot, monkeypatch, "What is your favourite colour?*")
    assert "What is your favourite colour?" in bot.unanswered_questions


def test_a_stale_pagination_element_is_reread_not_taken_for_a_dead_browser(bot, monkeypatch):
    '''Live, the 11-19 run ended mid-way with "The browser window was closed or the session became
    invalid" while Chrome was fine: the pagination element read at the top of the page had gone
    stale after ~25 jobs, StaleElementReferenceException is a WebDriverException, and the page
    turn only expected NoSuchElementException.'''
    from selenium.common.exceptions import StaleElementReferenceException
    clicked = []
    next_button = FakeElement()
    fresh = FakeElement(children={".//button[@aria-label='Page 3']": next_button})

    class Stale(FakeElement):
        def find_element(self, by, locator):
            raise StaleElementReferenceException("stale element reference")

    monkeypatch.setattr(bot, "get_page_info", lambda: (fresh, 2))
    monkeypatch.setattr(bot, "click_through_overlays", lambda element: clicked.append(element))
    assert bot.turn_page(Stale(), 2) is True
    assert clicked == [next_button]


def test_no_next_page_button_means_the_end_of_the_results(bot, monkeypatch):
    monkeypatch.setattr(bot, "click_through_overlays", lambda element: pytest.fail("clicked something"))
    assert bot.turn_page(FakeElement(), 5) is False


def test_a_pagination_element_that_stays_unreadable_ends_the_search_not_the_run(bot, monkeypatch):
    from selenium.common.exceptions import StaleElementReferenceException

    class Stale(FakeElement):
        def find_element(self, by, locator):
            raise StaleElementReferenceException("stale element reference")

    monkeypatch.setattr(bot, "get_page_info", lambda: (None, None))
    assert bot.turn_page(Stale(), 2) is False                 # returns, does not raise

    monkeypatch.setattr(bot, "get_page_info", lambda: (Stale(), 2))
    assert bot.turn_page(Stale(), 2) is False                 # still stale after one re-read


# ---- radio questions on the 2026 modal (captured from a real stalled "Additional Questions" step) ----
class RadioOption(FakeElement):
    '''One native <input type=radio> as the 2026 modal renders it: no useful value attribute, an
    EMPTY <label for>, and the words "Yes" / "No" in a <p> in its row, two <div>s up.'''

    def __init__(self, id, option_text, question):
        row = FakeElement(children={".//p": FakeElement(text=option_text)})
        super().__init__(children={"./ancestor::div[2]": row})
        self.id, self.question, self.selected = id, question, False

    def get_attribute(self, name):
        return {"id": self.id, "value": "on", "aria-label": self.question}.get(name)

    def is_selected(self):
        return self.selected


def new_layout_radio(question_text, *option_texts):
    '''(container, options) shaped like the captured step. The easyApplyFieldFocus_ key is on the
    container itself, which already holds its own <p>, unlike a text box.'''
    question = question_text.rstrip("*").strip()
    options = [RadioOption(f"_r_{n}_", text, question) for n, text in enumerate(option_texts)]
    fieldset = FakeElement(children={"input": options,
                                     **{f'.//label[@for="{o.id}"]': FakeElement(text="") for o in options}})
    container = FakeElement(children={
        "./p": [FakeElement(text=question_text)],
        ".//fieldset[@role='radiogroup']": fieldset,
        ".//label[@for]": FakeElement(text=""),      # the first option's empty label is found first
        ARIA_FIELD_XPATH: options[0],                # every radio input repeats the question as its aria-label
        ".//p": FakeElement(text=question_text),
    })
    return container, options


class ClickRecorder:
    def __init__(self):
        self.clicked, self._target = [], None

    def move_to_element(self, element):
        self._target = element
        return self

    def click(self):
        self.clicked.append(self._target)
        return self

    def perform(self):
        return None


def test_a_radio_question_is_its_own_container_not_merged_into_its_parent(bot):
    '''Taking the parent for every field merged every question on the step into one container, in
    which no radio group was recognised - so the form stalled with no question seen at all.'''
    container, _ = new_layout_radio("Do you have experience with low-code?*", "Yes", "No")
    text_wrapper, text_parent, _ = new_layout_question("What is your notice period?*")
    assert bot.find_question_elements(new_layout_modal(bot, container, text_wrapper)) == [container, text_parent]


def test_a_radio_question_is_not_read_as_empty_because_its_option_labels_are(bot):
    container, _ = new_layout_radio("Do you have experience with low-code?*", "Yes", "No")
    assert bot.read_question_label(container) == "Do you have experience with low-code?"


def test_radio_option_text_comes_from_the_row_when_the_label_is_empty(bot):
    container, options = new_layout_radio("Q?*", "Yes", "No")
    fieldset = container.children[".//fieldset[@role='radiogroup']"]
    assert [bot.radio_option_text(fieldset, o) for o in options] == ["Yes", "No"]


def run_radio_question(bot, monkeypatch, container):
    recorder = ClickRecorder()
    monkeypatch.setattr(bot, "actions", recorder)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    questions = bot.answer_questions(new_layout_modal(bot, container), set(), "Chennai")
    return recorder.clicked, questions


def test_a_configured_radio_answer_is_clicked_on_the_new_modal(bot, monkeypatch):
    '''Yes/No questions are among the commonest on Easy Apply, and every one was invisible here.'''
    container, options = new_layout_radio("Are you legally authorized to work in India?*", "Yes", "No")
    monkeypatch.setattr(bot, "work_authorization_answer", lambda label: "Yes")
    clicked, questions = run_radio_question(bot, monkeypatch, container)
    assert clicked == [options[0]], "did not click the Yes option"
    assert any("Are you legally authorized" in entry[0] for entry in questions)


def test_a_radio_question_with_no_configured_answer_is_left_alone_not_guessed(bot, monkeypatch):
    '''Never click whatever is first: that submits a made-up answer to a real employer.'''
    container, _ = new_layout_radio("Prior experience with low-code platforms is required.*", "Yes", "No")
    monkeypatch.setattr(bot, "work_authorization_answer", lambda label: None)
    monkeypatch.setattr(bot, "answer_common_questions", lambda label, answer: answer)
    bot.unanswered_questions.clear()
    clicked, _ = run_radio_question(bot, monkeypatch, container)
    assert clicked == []
    assert any("low-code" in q for q in bot.unanswered_questions)


def test_a_radio_click_falls_back_to_the_dom_when_a_real_click_is_refused(bot, monkeypatch):
    '''The native input is an invisible box under its label, so a real click can be refused.'''
    from selenium.common.exceptions import MoveTargetOutOfBoundsException
    scripts = []

    class Refusing:
        def move_to_element(self, element):
            raise MoveTargetOutOfBoundsException("target out of bounds")

    monkeypatch.setattr(bot, "actions", Refusing())
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(
        execute_script=lambda script, *args: scripts.append((script, args))))
    option = RadioOption("_r_0_", "Yes", "Q?")
    bot.click_radio(option)
    assert len(scripts) == 1 and "click()" in scripts[0][0] and scripts[0][1] == (option,)


def test_every_stalled_form_gets_its_own_dump_up_to_a_cap(bot):
    '''One dump per run kept only the first stall. The first live stall was a CTC box LinkedIn
    rejected; the second had no recognised question at all, and its markup was never saved, so
    there was nothing to fix it from.'''
    source = inspect.getsource(bot.apply_to_jobs)
    assert bot.MAX_STUCK_DUMPS >= 5
    assert 'f"debug_easy_apply_stuck_{job_id}.html"' in source, "dumps overwrite each other again"
    assert "saved_stuck < MAX_STUCK_DUMPS" in source


def test_a_failed_submit_click_is_never_recorded_as_applied(bot):
    '''When Submit could not be clicked and nothing else was flagged, no reason was set, nothing
    raised, and the job fell through to submitted_jobs() as "Easy Applied" with Date Applied
    "Pending" and was counted in the summary, though nothing had been sent. One such row
    (job 4471277293) is in the real history.'''
    source = inspect.getsource(bot.apply_to_jobs)
    failed = source.split("Since, Submit Application failed", 1)[1] \
                   .split("if discard_reason: raise Exception(discard_reason)", 1)[0]
    assert 'discard_reason = "Failed to click Submit application' in failed
    assert 'if errored == "nose"' not in failed, "the reason is conditional again"


# ------------------------------ K: whole-word bad words ----------------------------
@pytest.mark.parametrize("text, words, expected", [
    ("Senior JavaScript Engineer", ["java"], None),          # the #95 bug: java != javascript
    ("Strong Java and Spring experience", ["java"], "java"),
    ("Backend role, ASP.NET Core", [".NET"], ".NET"),        # leading dot must still match
    ("We use .NETWORKING gear", [".NET"], None),
    ("No C2C please", ["No C2C"], "No C2C"),                 # multi-word phrases still work
    ("Must be a US Citizen", ["us citizen"], "us citizen"),  # case insensitive
    ("Rubyists welcome", ["Ruby"], None),
])
def test_find_bad_word_matches_whole_words_only(bot, text, words, expected):
    assert bot.find_bad_word(text, words) == expected


def test_a_javascript_job_is_not_skipped_by_the_bad_word_java(bot, monkeypatch):
    monkeypatch.setattr(bot, "bad_words", ["java"])
    monkeypatch.setattr(bot, "security_clearance", True)     # keep the clearance scan out of it
    monkeypatch.setattr(bot, "current_experience", -1)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "find_by_class",
                        lambda *a, **k: FakeElement(text="Senior JavaScript engineer, React and Node."))

    description, experience, skip, reason, message = bot.get_job_description()

    assert skip is False
    assert description.startswith("Senior JavaScript")


# ------------------------- F: recommended_wait was inverted ------------------------
def test_recommended_filter_wait_is_not_inverted(bot):
    assert bot.recommended_filter_wait(1) == 1    # the default click_gap must still pause
    assert bot.recommended_filter_wait(3) == 1
    assert bot.recommended_filter_wait(0) == 0    # only "no click gap" means no pause


# -------------------- B: an unreadable job description must skip -------------------
def test_unreadable_job_description_skips_the_job(bot, monkeypatch):
    def boom(*args, **kwargs):
        raise NoSuchElementException("jobs-box__html-content")

    monkeypatch.setattr(bot, "find_by_class", boom)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)

    description, experience, skip, reason, message = bot.get_job_description()

    assert description == "Unknown"
    assert skip is True          # never apply to a job whose description we never read
    assert reason and message


# ------------------ H: a run where nothing applied must not report zeros -----------
def test_non_easy_apply_job_is_counted_as_skipped(bot, monkeypatch):
    monkeypatch.setattr(bot, "easy_apply_only", True)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "skip_count", 0)

    skip, link, tabs = bot.external_apply(object(), "1", "link", "resume", None, "Easy Applied", "shot")

    assert skip is True
    assert bot.skip_count == 1


# --------------------------- C: resilient Easy Apply detection ---------------------
def test_easy_apply_detection_is_an_ordered_fallback_list(bot):
    xpaths = [xpath for _, xpath in bot.easy_apply_locators]
    assert len(xpaths) > 1                                   # fallbacks, not one brittle locator
    # Measured 2026-09-09: `id="jobs-apply-button-id"` is on the real button and is the most
    # stable anchor there is, so it leads. The openSDUIApplyFlow flag was NOT in the captured
    # DOM, so it is kept only as one of the fallbacks.
    assert "jobs-apply-button-id" in xpaths[0]
    assert any("openSDUIApplyFlow=true" in xpath for xpath in xpaths)
    assert not any("artdeco-button--3" in xpath for xpath in xpaths)

    source = open(os.path.join(os.path.dirname(__file__), os.pardir, "runAiBot.py"), encoding="utf-8").read()
    assert "artdeco-button--3" not in source                 # the size token is gone everywhere


# ------------------------------- M: the no-submit flag -----------------------------
def test_stop_before_submit_setting_is_always_defined(bot):
    assert isinstance(bot.stop_before_submit, bool)


# ------------------------- N: survey and company-by-company mode ---------------------
def test_survey_csv_round_trips_into_company_list_most_postings_first(bot, tmp_path, monkeypatch):
    survey = tmp_path / "survey.csv"
    monkeypatch.setattr(bot, "survey_file_name", str(survey))
    monkeypatch.setattr(bot, "target_companies", [])
    bot.write_company_survey({
        "Small Co": {"postings_seen": 1, "actively_hiring_signal": False, "sample_titles": {"Analyst"}},
        "Big Co": {"postings_seen": 7, "actively_hiring_signal": True, "sample_titles": {"Developer"}},
    })
    assert bot.load_target_companies() == ["Big Co", "Small Co"]


def test_explicit_target_companies_win_over_the_survey(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "survey_file_name", str(tmp_path / "survey.csv"))
    monkeypatch.setattr(bot, "target_companies", ["Microsoft"])
    assert bot.load_target_companies() == ["Microsoft"]


def test_no_targets_and_no_survey_gives_an_empty_list(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "survey_file_name", str(tmp_path / "missing.csv"))
    monkeypatch.setattr(bot, "target_companies", [])
    assert bot.load_target_companies() == []


# ------------------------------- O: referral requests --------------------------------
def test_referral_note_fills_placeholders_and_fits_linkedins_limit(bot, monkeypatch):
    monkeypatch.setattr(bot, "first_name", "Lokesh")
    monkeypatch.setattr(bot, "last_name", "J")
    note = bot.referral_note("Asha", "Power BI Developer", "Philips")
    assert note.startswith("Hi Asha,") and "Power BI Developer" in note and "Philips" in note and "Lokesh J" in note
    long_note = bot.referral_note("Asha", "Data Analyst II (Sharepoint/ PowerApps/ Power Automate Developer)- Only Bangalore Based Candidates", "AtkinsRealis")
    assert len(long_note) <= bot.REFERRAL_NOTE_LIMIT
    assert long_note.endswith("Lokesh J")


def test_referral_targets_are_only_submitted_easy_applies_one_per_company(bot, tmp_path, monkeypatch):
    applied = tmp_path / "applied.csv"
    applied.write_text(
        "Company,Title,External Job link,Date Applied,HR Link,HR Name\n"
        "GIVA,Business Analyst,Easy Applied,2026-10-01 11:50:09,Unknown,Unknown\n"
        "Philips,Power BI Developer,https://careers.philips.com/x,Pending,Unknown,Unknown\n"
        "GIVA,Data Analyst,Easy Applied,2026-10-01 11:55:00,Unknown,Unknown\n"
        "Jobgether,Data Engineer,Easy Applied,Pending,Unknown,Unknown\n"
        "Kaufman Rossin,Analyst,Easy Applied,2026-10-01 11:58:00,Unknown,Unknown\n",
        encoding="utf-8")
    monkeypatch.setattr(bot, "file_name", str(applied))
    # This test is about the Easy-Applied / one-per-company filter, not the recency window,
    # so take the window out of it - these fixed dates would otherwise age out of any window.
    monkeypatch.setattr(bot, "referral_recent_days", 0)
    targets = bot.load_referral_targets()
    assert [(t["Company"], t["Title"]) for t in targets] == [("Kaufman Rossin", "Analyst"), ("GIVA", "Data Analyst")]


@pytest.mark.parametrize("full, short", [
    ("ZettaMine Labs Pvt. Ltd.", "ZettaMine Labs"),
    ("Weekday AI (YC W21)", "Weekday AI"),
    ("FyerX Global Private Limited", "FyerX Global"),
    ("Smart IMS Inc.", "Smart IMS"),
    ("Kaufman Rossin", "Kaufman Rossin"),
    ("GIVA", "GIVA"),
])
def test_company_names_are_shortened_to_what_profiles_show(bot, full, short):
    assert bot.short_company_name(full) == short


def test_referral_history_counts_only_sent_requests_towards_limits(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "referral_file_name", str(tmp_path / "referrals.csv"))
    bot.record_referral("GIVA", "Business Analyst", "Asha K", "https://www.linkedin.com/in/asha", "Hiring team", "Sent with note")
    bot.record_referral("GIVA", "Business Analyst", "Ravi M", "https://www.linkedin.com/in/ravi", "People search", "Skipped - no Connect button (already connected, pending, or follow-only)")
    contacted, per_company, today = bot.load_referral_history()
    assert contacted == {"https://www.linkedin.com/in/asha"}
    assert per_company == {"GIVA": 1}
    assert today == 1


# -------- after the apply click, wait for EITHER outcome, neither is instant ---------
def test_a_slow_external_tab_is_still_seen_as_external(bot, monkeypatch):
    '''The window count used to be read once, about a second after the click. LinkedIn's
    redirect tab is often not open yet then, so an external job matched neither outcome and was
    recorded as a failure while its tab was still on the way - seen live on an 80% job.'''
    polls = {"n": 0}

    class Driver:
        @property
        def window_handles(self):
            polls["n"] += 1
            return ["a", "b"] if polls["n"] > 4 else ["a"]      # tab opens late

    monkeypatch.setattr(bot, "driver", Driver())
    monkeypatch.setattr(bot, "find_easy_apply_modal", lambda timeout=0.4: None)
    assert bot.wait_for_apply_outcome(1, timeout=5) == "external"
    assert polls["n"] > 1, "gave up after a single look"


def test_an_opened_modal_is_reported_as_modal(bot, monkeypatch):
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(window_handles=["a"]))
    monkeypatch.setattr(bot, "find_easy_apply_modal", lambda timeout=0.4: FakeElement())
    assert bot.wait_for_apply_outcome(1, timeout=5) == "modal"


def test_neither_outcome_reports_nothing_rather_than_hanging(bot, monkeypatch):
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(window_handles=["a"]))
    monkeypatch.setattr(bot, "find_easy_apply_modal", lambda timeout=0.4: None)
    assert bot.wait_for_apply_outcome(1, timeout=1) == "nothing"


# ---------- the Easy Apply modal must be recognised on the 2026 layout --------------
def test_modal_locator_matches_the_sdui_screen_and_the_old_class(bot):
    '''LinkedIn's 2026 job pages render the modal as an SDUI screen with randomised classes and
    no "jobs-easy-apply-modal" anywhere. Checking only that class meant the modal opened, the
    bot could not see it, and every Easy Apply job fell through to the external path and was
    recorded "Failed to apply!" - a run submitting zero applications while the modal worked.'''
    xp = bot.EASY_APPLY_MODAL_XPATH
    assert "easyapply.EasyApply" in xp, "new SDUI modal screen not matched"
    assert "jobs-easy-apply-modal" in xp, "classic layout no longer matched"


def test_modal_is_open_is_false_when_nothing_is_displayed(bot, monkeypatch):
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=lambda by, xp: []))
    assert bot.easy_apply_modal_is_open() is False


def test_modal_is_open_is_true_for_a_displayed_sdui_modal(bot, monkeypatch):
    shown = FakeElement()
    shown.is_displayed = lambda: True
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=lambda by, xp: [shown]))
    assert bot.easy_apply_modal_is_open() is True


def test_modal_is_open_ignores_a_hidden_match(bot, monkeypatch):
    hidden = FakeElement()
    hidden.is_displayed = lambda: False
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=lambda by, xp: [hidden]))
    assert bot.easy_apply_modal_is_open() is False


def test_discard_targets_the_real_dismiss_label_exactly(bot):
    '''The new close button is aria-label="Dismiss" with no data-test attribute. It must match
    exactly: "Dismiss <job title> job" is a job-card button behind the modal, not the modal's.'''
    src = inspect.getsource(bot.discard_job)
    assert "@aria-label='Dismiss'" in src
    assert "contains(@aria-label,'Dismiss')" not in src


# --------- the Apply button gets longer than the shared 5s wait to appear -----------
def test_apply_button_waits_longer_than_the_shared_wait(bot):
    '''The details pane is built after the card click and the Apply button arrives last. At the
    shared 5s this timed out on roughly one job in six, reporting "Failed to apply!" for jobs
    that were perfectly applicable.'''
    assert bot.APPLY_BUTTON_TIMEOUT >= 15


def test_apply_button_selector_accepts_both_renders(bot):
    '''Stable id first, old class as the fallback, and never the design-system size token.'''
    xp = bot.apply_button_xpath
    assert "jobs-apply-button-id" in xp and "jobs-apply-button" in xp
    assert "artdeco-button--" not in xp


# ------------- a dialog over the results list must not end the whole run -------------
def test_intercepted_card_click_is_retried_after_closing_the_dialog(bot, monkeypatch):
    '''Live, an open <dialog data-testid="dialog"> intercepted every job-card click and the
    exception travelled out of apply_to_jobs, ending a run across all 12 search terms.'''
    from selenium.common.exceptions import ElementClickInterceptedException
    dismissed = []
    clicks = []

    class Card(FakeElement):
        def __init__(self):
            super().__init__()
            self.children = {".//p": [FakeElement(text="Power Platform Developer"),
                                      FakeElement(text="Acme"),
                                      FakeElement(text="Chennai (Remote)")]}

        def click(self):
            clicks.append(1)
            if len(clicks) == 1:                 # blocked until the dialog is closed
                raise ElementClickInterceptedException("element click intercepted")

        def get_dom_attribute(self, name):
            return "job-card-component-ref-1" if name == "componentkey" else None

    monkeypatch.setattr(bot, "scroll_to_view", lambda *a, **k: None)
    monkeypatch.setattr(bot, "buffer", lambda *a, **k: None)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "card_job_id", lambda card: "1")
    monkeypatch.setattr(bot, "split_location", lambda text: ("Chennai", "Remote"))
    monkeypatch.setattr(bot, "dismiss_open_dialog", lambda: dismissed.append(1) or True)

    job_id, title, company, _loc, _style, skip = bot.get_ai_search_card_details(Card(), set(), set())
    assert dismissed == [1], "did not try to close the dialog"
    assert len(clicks) == 2, "did not retry the click after closing the dialog"
    assert (title, company, skip) == ("Power Platform Developer", "Acme", False)


def test_a_click_nothing_can_unblock_falls_back_to_a_dom_click(bot, monkeypatch):
    '''When the overlay cannot be closed, the click still has to land: a DOM click reaches the
    element whatever is painted on top. Live, giving up here cost a whole run.'''
    from selenium.common.exceptions import ElementClickInterceptedException
    scripts = []

    class Blocked(FakeElement):
        def click(self):
            raise ElementClickInterceptedException("element click intercepted")

    target = Blocked()
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "dismiss_open_dialog", lambda: False)
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(
        execute_script=lambda script, *args: scripts.append((script, args))))

    bot.click_through_overlays(target)
    assert len(scripts) == 1 and "click()" in scripts[0][0]
    assert scripts[0][1] == (target,)


def test_dismiss_open_dialog_reports_false_when_nothing_actually_closed(bot, monkeypatch):
    '''It used to click any "Close" button anywhere on the page - LinkedIn's messaging overlay
    is also role="dialog" - then report success while the real blocker stayed open, so the
    caller retried a still-blocked click.'''
    stuck = FakeElement()
    stuck.is_displayed = lambda: True
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "buffer", lambda *a, **k: None)
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(
        find_elements=lambda by, xpath: [stuck],      # still there after the close attempt
        execute_script=lambda script, *args: None))
    assert bot.dismiss_open_dialog() is False


def test_dismiss_open_dialog_reports_true_once_the_dialog_is_gone(bot, monkeypatch):
    shown = FakeElement()
    shown.is_displayed = lambda: True
    calls = {"n": 0}

    def find_elements(by, xpath):
        calls["n"] += 1
        return [shown] if calls["n"] == 1 else []      # gone on the verification pass

    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "buffer", lambda *a, **k: None)
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(
        find_elements=find_elements, execute_script=lambda script, *args: None))
    assert bot.dismiss_open_dialog() is True


# ------------------- referral targets: recent companies, correctly ordered ----------
def write_history(path, rows):
    '''An applied-jobs history CSV holding just the columns load_referral_targets() reads.'''
    import csv as _csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=["Company", "Title", "Date Applied", "External Job link"])
        w.writeheader()
        for company, date in rows:
            w.writerow({"Company": company, "Title": "Developer",
                        "Date Applied": date, "External Job link": "Easy Applied"})


@pytest.fixture
def history(bot, tmp_path, monkeypatch):
    path = tmp_path / "applied.csv"
    monkeypatch.setattr(bot, "file_name", str(path))
    return path


LOST = "Unknown (timestamp lost to an Excel edit on 2026-10-06)"


def test_undated_rows_no_longer_jump_ahead_of_real_dates(bot, monkeypatch, history):
    '''"Unknown (timestamp..." used to sort above every "2026-.." date, because "U" > "2",
    so referrals began at the oldest, least certain companies instead of the newest.'''
    now = datetime.now()
    write_history(history, [
        ("OldUndated", LOST),
        ("AppliedToday", now.strftime("%Y-%m-%d %H:%M:%S.%f")),
        ("AppliedYesterday", (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f")),
    ])
    monkeypatch.setattr(bot, "referral_recent_days", 0)       # no window: keep everything
    assert [r["Company"] for r in bot.load_referral_targets()] == [
        "AppliedToday", "AppliedYesterday", "OldUndated"]


def test_only_companies_inside_the_recent_window_are_asked(bot, monkeypatch, history):
    now = datetime.now()
    write_history(history, [
        ("Fresh", (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S.%f")),
        ("SixWeeksAgo", (now - timedelta(days=42)).strftime("%Y-%m-%d %H:%M:%S.%f")),
        ("Undated", LOST),
    ])
    monkeypatch.setattr(bot, "referral_recent_days", 7)
    # An unreadable date cannot be shown to be recent, so it fails the window too.
    assert [r["Company"] for r in bot.load_referral_targets()] == ["Fresh"]


def test_one_entry_per_company_keeping_its_newest_application(bot, monkeypatch, history):
    now = datetime.now()
    write_history(history, [
        ("Acme", (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S.%f")),
        ("Acme", (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f")),
    ])
    monkeypatch.setattr(bot, "referral_recent_days", 7)
    targets = bot.load_referral_targets()
    assert len(targets) == 1
    assert bot.applied_timestamp(targets[0]).date() == (now - timedelta(days=1)).date()


@pytest.mark.parametrize("raw", [LOST, "", "Pending", "not a date", None])
def test_applied_timestamp_is_none_for_anything_that_is_not_a_timestamp(bot, raw):
    assert bot.applied_timestamp({"Date Applied": raw}) is None


def test_applied_timestamp_reads_the_format_the_bot_writes(bot):
    assert (bot.applied_timestamp({"Date Applied": "2026-10-07 10:45:07.648837"})
            == datetime(2026, 10, 7, 10, 45, 7, 648837))


# --------------------- the monthly note quota: skip rather than send blank -----------
@pytest.fixture
def quota_used_up(bot, monkeypatch):
    '''send_connection_request() on a profile where LinkedIn offers "Send without a note".

    That is what it shows once the free monthly personalised-invite quota is spent: the
    Add-a-note button is there, but clicking it yields no textarea.
    '''
    clicked = []

    class Btn(FakeElement):
        def __init__(self, label):
            super().__init__(text=label)
            self.label = label

        def click(self):
            clicked.append(self.label)

    connect = Btn("connect")
    connect.get_attribute = lambda name: (
        "https://www.linkedin.com/custom-invite/?vanityName=x" if name == "href" else None)

    buttons = {"add a note": Btn("add a note"), "send without": Btn("send without")}

    class Driver:
        page_source = ""

        def find_elements(self, by, xpath):
            return [connect] if "to connect" in xpath else []

    monkeypatch.setattr(bot, "driver", Driver())
    monkeypatch.setattr(bot, "pick_first_displayed", lambda els: els[0] if els else None)
    monkeypatch.setattr(bot, "scroll_to_view", lambda *a, **k: None)
    monkeypatch.setattr(bot, "buffer", lambda *a, **k: None)
    monkeypatch.setattr(bot, "save_page_once", lambda *a, **k: None)
    monkeypatch.setattr(bot, "click_gap", 0)
    monkeypatch.setattr(bot, "actions", types.SimpleNamespace(
        send_keys=lambda *a: types.SimpleNamespace(perform=lambda: None)))
    # No note textarea ever appears - this is the quota-exhausted page.
    monkeypatch.setattr(bot, "invite_button",
                        lambda scope, label, exact=False: buttons.get(label))
    return clicked


def test_note_quota_used_up_skips_the_person_when_a_note_is_required(bot, monkeypatch, quota_used_up):
    monkeypatch.setattr(bot, "referral_require_note", True)
    result = bot.send_connection_request("Asha Kumar", "Hi Asha, I just applied...")
    assert result.startswith("Skipped - note quota used up")
    assert "send without" not in quota_used_up, "sent a noteless request anyway"


def test_note_quota_used_up_still_sends_when_a_note_is_not_required(bot, monkeypatch, quota_used_up):
    monkeypatch.setattr(bot, "referral_require_note", False)
    result = bot.send_connection_request("Asha Kumar", "Hi Asha, I just applied...")
    assert result.startswith("Sent without note")
    assert "send without" in quota_used_up


def test_a_quota_skip_does_not_count_towards_the_daily_limit(bot, tmp_path, monkeypatch):
    '''Only rows starting with "Sent" count, so a skipped person is neither charged against
    today's limit nor marked contacted - they can be asked once the quota resets.'''
    monkeypatch.setattr(bot, "referral_file_name", str(tmp_path / "referrals.csv"))
    bot.record_referral("GIVA", "Analyst", "Asha K", "https://www.linkedin.com/in/asha",
                        "People search", "Skipped - note quota used up (referral_require_note is on)")
    contacted, per_company, today = bot.load_referral_history()
    assert contacted == set()
    assert per_company == {}
    assert today == 0


# ------------------------------- N: location via URL, not the UI box ----------------
def test_jobs_search_url_includes_both_keywords_and_location(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_location", "Singapore")
    url = bot.jobs_search_url("Power Platform Developer")
    # The 2026-11 AI search page drops location=, so the location now rides in the query.
    assert url == "https://www.linkedin.com/jobs/search-results/?keywords=Power%20Platform%20Developer%20in%20Singapore"


def test_jobs_search_url_with_no_keywords_for_company_mode(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_location", "Singapore")
    url = bot.jobs_search_url()
    assert url == "https://www.linkedin.com/jobs/search/?location=Singapore"


def test_jobs_search_url_omits_location_when_blank(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_location", "")
    url = bot.jobs_search_url("Data Analyst")
    assert url == "https://www.linkedin.com/jobs/search-results/?keywords=Data%20Analyst"
    assert "location=" not in url


# ------------------------------- O: multi-location search -----------------------------
def test_locations_to_search_falls_back_to_single_location(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_locations", [])
    monkeypatch.setattr(bot, "search_location", "India")
    assert bot.locations_to_search() == ["India"]


def test_locations_to_search_uses_the_list_when_set(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_locations", ["Singapore", "Chennai", "Bengaluru"])
    monkeypatch.setattr(bot, "search_location", "India")
    assert bot.locations_to_search() == ["Singapore", "Chennai", "Bengaluru"]
