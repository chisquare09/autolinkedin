import csv
import io
import json
import re
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).parents[1]
PHANTOM_SCRIPT = ROOT / "apps_scripts" / "PhantomAutomation.gs"
SUMMARY_SCRIPT = ROOT / "apps_scripts" / "SummarizationAutomation.gs"
GUIDE = ROOT / "docs" / "testing_guide.md"


def normalize_profile_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    match = re.match(r"^https?://([^/?#]+)([^?#]*)", raw, re.IGNORECASE)
    if not match or match.group(1).lower() not in {
        "linkedin.com",
        "www.linkedin.com",
    }:
        return ""
    path = match.group(2).rstrip("/").lower()
    return "https://www.linkedin.com" + re.sub(r"/posts$", "", path)


def stable_post_key(row, profile):
    post_url = str(row.get("postUrl") or row.get("sharedPostUrl") or "").strip()
    if post_url:
        return "url:" + re.sub(r"[?#].*", "", post_url).rstrip("/")
    content = re.sub(
        r"\s+",
        " ",
        str(row.get("postContent") or "").strip().lower(),
    )
    post_date = str(
        row.get("postDate")
        or row.get("postTimestamp")
        or row.get("timestamp")
        or ""
    ).strip()
    if not profile or not post_date or not content:
        return ""
    return "fallback:{}|{}|{}".format(profile, post_date[:10], content)


def closed_period(current, week_start):
    start_index = {
        "SUNDAY": 6,
        "MONDAY": 0,
        "TUESDAY": 1,
        "WEDNESDAY": 2,
        "THURSDAY": 3,
        "FRIDAY": 4,
        "SATURDAY": 5,
    }[week_start]
    days_since_start = (current.weekday() - start_index) % 7
    current_start = current - timedelta(days=days_since_start)
    end = current_start - timedelta(days=1)
    start = end - timedelta(days=6)
    return start, end


def validate_summary_response(response, row_ids):
    summaries = response.get("summaries")
    if not isinstance(summaries, list) or len(summaries) != len(row_ids):
        raise ValueError("invalid summary count")
    expected = set(row_ids)
    seen = set()
    result = {}
    for item in summaries:
        row_id = item.get("row_id")
        if row_id not in expected or row_id in seen:
            raise ValueError("invalid row id")
        sentences = item.get("sentences")
        if not isinstance(sentences, list) or not 1 <= len(sentences) <= 3:
            raise ValueError("invalid sentence array")
        if any(
            not isinstance(sentence, str)
            or not sentence.strip()
            or not re.search(r'[.!?]["\')\]]?$', sentence.strip())
            for sentence in sentences
        ):
            raise ValueError("incomplete sentence")
        text = " ".join(sentence.strip() for sentence in sentences)
        if len(text.split()) > 100:
            raise ValueError("summary exceeds 100 words")
        seen.add(row_id)
        result[row_id] = text
    if seen != expected:
        raise ValueError("missing row id")
    return result


class AppsScriptWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.phantom_source = PHANTOM_SCRIPT.read_text()
        cls.summary_source = SUMMARY_SCRIPT.read_text()
        cls.guide_source = GUIDE.read_text()

    def test_apps_script_contains_required_properties_and_three_output_columns(self):
        for property_name in (
            "PHANTOMBUSTER_API_KEY",
            "PHANTOMBUSTER_AGENT_ID",
            "GEMINI_API_KEY",
            "GEMINI_MODEL",
            "TIMEZONE",
            "WEEK_START_DAY",
            "SCHEDULE_DAY",
            "SCHEDULE_TIME",
        ):
            self.assertIn("'" + property_name + "'", self.phantom_source)

        self.assertIn("'content_summary',", self.phantom_source)
        self.assertIn("'processing_status',", self.phantom_source)
        self.assertIn("'processing_error'", self.phantom_source)
        for removed_column in (
            "'processed_at'",
            "'source_post_key'",
        ):
            self.assertNotIn(removed_column, self.phantom_source)

    def test_closed_period_supports_different_week_and_schedule_days(self):
        # Sunday-start reporting run on Monday processes the prior Sunday-Saturday.
        start, end = closed_period(date(2026, 10, 19), "SUNDAY")
        self.assertEqual(start.isoformat(), "2026-10-11")
        self.assertEqual(end.isoformat(), "2026-10-17")
        self.assertIn("WEEK_START_DAY", self.guide_source)
        self.assertIn("SCHEDULE_DAY", self.guide_source)
        self.assertIn("function reportingDayIndex_", self.phantom_source)
        self.assertIn("const startDay = reportingDayIndex_(weekStartDay);", self.phantom_source)

    def test_customer_urls_are_normalized_and_invalid_hosts_are_rejected(self):
        self.assertEqual(
            normalize_profile_url("linkedin.com/company/acme/"),
            "https://www.linkedin.com/company/acme",
        )
        self.assertEqual(
            normalize_profile_url("https://www.linkedin.com/company/acme/posts"),
            "https://www.linkedin.com/company/acme",
        )
        self.assertEqual(normalize_profile_url("https://example.com/acme"), "")

    def test_combined_csv_import_only_keeps_new_stable_keys(self):
        csv_text = """profileUrl,postUrl,postDate,postContent
https://www.linkedin.com/company/acme/,https://linkedin.com/feed/update/1,2026-10-12T00:00:00Z,First
https://www.linkedin.com/company/acme/,https://linkedin.com/feed/update/1,2026-10-12T00:00:00Z,First duplicate
https://www.linkedin.com/company/acme/,https://linkedin.com/feed/update/2,2026-10-13T00:00:00Z,Second
"""
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        already_imported = {"url:https://linkedin.com/feed/update/1"}
        new_keys = []
        seen = set()
        for row in rows:
            profile = normalize_profile_url(row["profileUrl"])
            key = stable_post_key(row, profile)
            if key and key not in already_imported and key not in seen:
                seen.add(key)
                new_keys.append(key)
        self.assertEqual(new_keys, ["url:https://linkedin.com/feed/update/2"])

    def test_summary_accepts_exactly_100_words(self):
        sentence = " ".join(["word"] * 99) + "."
        response = {"summaries": [{"row_id": 2, "sentences": [sentence]}]}
        self.assertEqual(len(validate_summary_response(response, [2])[2].split()), 99)

        sentence = " ".join(["word"] * 100) + "."
        response = {"summaries": [{"row_id": 2, "sentences": [sentence]}]}
        self.assertEqual(len(validate_summary_response(response, [2])[2].split()), 100)

    def test_summary_rejects_more_than_100_words_and_invalid_rows(self):
        sentence = " ".join(["word"] * 101) + "."
        with self.assertRaisesRegex(ValueError, "100 words"):
            validate_summary_response(
                {"summaries": [{"row_id": 2, "sentences": [sentence]}]},
                [2],
            )
        with self.assertRaisesRegex(ValueError, "row id"):
            validate_summary_response(
                {"summaries": [{"row_id": 3, "sentences": ["Valid."]}]},
                [2],
            )

    def test_summary_contract_has_low_thinking_and_bounded_retry_rules(self):
        self.assertIn("thinkingConfig: {thinkingLevel: 'LOW'}", self.summary_source)
        self.assertIn("SUMMARY_MAX_TRANSPORT_ATTEMPTS = 3", self.summary_source)
        self.assertIn("SUMMARY_MAX_VALIDATION_ATTEMPTS = 2", self.summary_source)
        self.assertIn("isValidationError_", self.summary_source)
        self.assertIn("100 words", self.summary_source)
        self.assertIn("function hasSummaryColumns_(sheet)", self.summary_source)
        self.assertIn("if (sheet && hasSummaryColumns_(sheet)) return sheet;", self.summary_source)

    def test_manual_guide_identifies_live_only_cases(self):
        self.assertIn("PHANTOM_LAUNCH", self.guide_source)
        self.assertIn("GEMINI_SUMMARY", self.guide_source)
        self.assertIn("Prompt-injection and factuality behavior", self.guide_source)
        self.assertIn("_automation_log", self.guide_source)


if __name__ == "__main__":
    unittest.main()
