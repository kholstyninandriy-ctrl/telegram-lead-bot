"""Тести чистої логіки бота: телефони, відгуки, скоринг, парсинг, БД, пагінація.

Запуск:  python -m unittest discover -s tests -v
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_notes.db")
os.environ["SEARCH_CACHE_TTL_MIN"] = "60"

import db  # noqa: E402
import enrich  # noqa: E402
import places  # noqa: E402
import ui  # noqa: E402
from handlers_search import build_lead, strip_emoji  # noqa: E402
from phones import country_to_iso, digits_only, validate_phone  # noqa: E402
from reviews import analyze_reviews, review_text, score_lead  # noqa: E402


def iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


class PhoneTests(unittest.TestCase):
    def test_country_names_map_to_iso(self):
        self.assertEqual(country_to_iso("Turkey"), "TR")
        self.assertEqual(country_to_iso("україна"), "UA")
        self.assertEqual(country_to_iso("PT"), "PT")
        self.assertIsNone(country_to_iso("Narnia"))

    def test_national_number_with_country_hint(self):
        # Раніше в phonenumbers передавалась назва країни і такий номер не парсився
        result = validate_phone("0532 123 45 67", "Turkey")
        self.assertTrue(result["valid"])
        self.assertEqual(result["e164"], "+905321234567")

    def test_international_number(self):
        result = validate_phone("+380 44 123 45 67", "Ukraine")
        self.assertTrue(result["valid"])
        self.assertEqual(result["region"], "UA")

    def test_invalid_and_empty(self):
        self.assertFalse(validate_phone("123", "Ukraine")["valid"])
        self.assertEqual(validate_phone("", "")["formatted"], "—")
        self.assertEqual(digits_only("+90 (532) 123-45-67"), "905321234567")


class ReviewTests(unittest.TestCase):
    def test_no_reviews(self):
        result = analyze_reviews([])
        self.assertEqual(result["sentiment"], "невідомо")
        self.assertIsNone(result["days_since_review"])

    def test_fresh_positive(self):
        reviews = [
            {"rating": 5, "publishTime": iso_days_ago(3), "text": {"text": "Чудово, рекомендую"}},
            {"rating": 5, "publishTime": iso_days_ago(20), "text": {"text": "Excellent service"}},
        ]
        result = analyze_reviews(reviews)
        self.assertEqual(result["actuality_emoji"], "🟢")
        self.assertEqual(result["sentiment"], "позитивний")
        self.assertLess(result["days_since_review"], 10)

    def test_old_negative_and_closed(self):
        reviews = [
            {"rating": 1, "publishTime": iso_days_ago(400), "text": {"text": "Жахливо, закрито"}},
            {"rating": 2, "publishTime": iso_days_ago(500), "text": {"text": "terrible, rude"}},
        ]
        result = analyze_reviews(reviews)
        self.assertEqual(result["sentiment"], "негативний")
        self.assertTrue(result["closed_signal"])

    def test_review_text_formats(self):
        self.assertEqual(review_text({"text": {"text": "a"}}), "a")
        self.assertEqual(review_text({"text": "b"}), "b")
        self.assertEqual(review_text({}), "")


class ScoreTests(unittest.TestCase):
    def test_hot_lead_beats_cold_one(self):
        hot = {"phone_valid": True, "email": "a@b.com", "website": "", "days_since_review": 5,
               "rating": 3.9, "review_count": 12, "business_status": "OPERATIONAL"}
        cold = {"phone_valid": False, "website": "https://x.com", "days_since_review": 900,
                "rating": 4.9, "review_count": 900, "business_status": "OPERATIONAL"}
        self.assertGreater(score_lead(hot)[0], score_lead(cold)[0])

    def test_closed_business_is_penalised(self):
        base = {"phone_valid": True, "days_since_review": 10, "rating": 4.5, "review_count": 50}
        closed = dict(base, business_status="CLOSED_PERMANENTLY")
        self.assertGreater(score_lead(base)[0], score_lead(closed)[0] + 30)

    def test_score_within_bounds(self):
        for lead in ({}, {"phone_valid": True} , {"closed_signal": True}):
            score, mark = score_lead(lead)
            self.assertTrue(0 <= score <= 100)
            self.assertTrue(mark)


class EnrichParsingTests(unittest.TestCase):
    def test_mailto_wins_over_plain_text(self):
        html = '<a href="mailto:Boss@Shop.de">mail</a> support@other.com'
        self.assertEqual(enrich.pick_email(html), "boss@shop.de")

    def test_image_and_placeholder_emails_ignored(self):
        self.assertEqual(enrich.pick_email('<img src="logo@2x.png">'), "")
        self.assertEqual(enrich.pick_email("hi@example.com"), "")

    def test_instagram_service_paths_ignored(self):
        html = '<a href="https://instagram.com/p/abc"></a><a href="https://instagram.com/my.cafe/"></a>'
        self.assertEqual(enrich.pick_instagram(html), "my.cafe")

    def test_facebook_sharer_ignored(self):
        html = '<a href="https://facebook.com/sharer/x"></a><a href="https://facebook.com/mycafe"></a>'
        self.assertEqual(enrich.pick_facebook(html), "mycafe")

    def test_instagram_from_website_url(self):
        self.assertEqual(enrich.instagram_from_url("https://instagram.com/mybiz/?hl=uk"), "mybiz")
        self.assertEqual(enrich.instagram_from_url("https://mybiz.com"), "")


class UITests(unittest.TestCase):
    def test_escaping(self):
        self.assertEqual(ui.esc("Bar & <Grill>"), "Bar &amp; &lt;Grill&gt;")

    def test_split_keeps_lines_intact(self):
        text = "\n".join(f"рядок {i}" * 20 for i in range(200))
        parts = ui.split_message(text, limit=1000)
        self.assertTrue(all(len(part) <= 1000 for part in parts))
        self.assertEqual("".join(parts).replace("\n", ""), text.replace("\n", ""))

    def test_lead_card_escapes_dangerous_name(self):
        lead = {"name": "Pizza <b>_King_</b> & Co", "address": "вул. Тестова 1",
                "rating": 4.5, "review_count": 10, "score": 80, "score_mark": "🔥 гарячий",
                "phone_formatted": "+380 44 123 4567", "phone_emoji": "✅",
                "phone_note": "мобільний · UA", "actuality_emoji": "🟢",
                "actuality_label": "активний", "context_points": ["пункт"],
                "business_status": "OPERATIONAL"}
        card = ui.lead_card(lead, 1, 5)
        self.assertIn("Pizza &lt;b&gt;_King_&lt;/b&gt; &amp; Co", card)
        self.assertNotIn("<b>_King_", card)


class BuildLeadTests(unittest.TestCase):
    SAMPLE = {
        "id": "ChIJ123",
        "displayName": {"text": "Cafe *Star*"},
        "formattedAddress": "Istiklal 1, Istanbul",
        "rating": 4.2,
        "userRatingCount": 88,
        "businessStatus": "OPERATIONAL",
        "nationalPhoneNumber": "0532 123 45 67",
        "websiteUri": "https://cafestar.example",
        "googleMapsUri": "https://maps.google.com/?cid=1",
        "photos": [{"name": "places/x/photos/a"}, {"name": "places/x/photos/b"}],
        "reviews": [{"rating": 5, "publishTime": iso_days_ago(10), "text": {"text": "супер"}}],
    }

    def test_fields_extracted(self):
        lead = build_lead(self.SAMPLE, "cafe", "Turkey", "Istanbul")
        self.assertEqual(lead["name"], "Cafe *Star*")
        self.assertEqual(lead["place_id"], "ChIJ123")
        self.assertTrue(lead["phone_valid"])
        self.assertEqual(lead["phone_e164"], "+905321234567")
        self.assertEqual(len(lead["photo_names"]), 2)
        self.assertEqual(lead["sentiment"], "позитивний")

    def test_missing_fields_do_not_crash(self):
        lead = build_lead({}, "cafe", "Turkey", "Istanbul")
        self.assertEqual(lead["name"], "Без назви")
        self.assertFalse(lead["phone_valid"])

    def test_strip_emoji(self):
        self.assertEqual(strip_emoji("🇹🇷 Turkey"), "Turkey")
        self.assertEqual(strip_emoji("🏋️ Gym"), "Gym")
        self.assertEqual(strip_emoji("Beauty salon"), "Beauty salon")
        self.assertEqual(strip_emoji("🍕"), "🍕")  # тільки емодзі — лишаємо як є


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.ainit_db()
        self.user = 4242

    async def test_note_lifecycle(self):
        note_id = await db.aadd_note(self.user, "Pizza Bar", "+380441234567",
                                     "interested", "передзвонити", "place1")
        notes = await db.aget_notes(self.user)
        self.assertTrue(any(n["id"] == note_id for n in notes))

        filtered = await db.aget_notes(self.user, "interested")
        self.assertTrue(filtered)

        stats = await db.anotes_stats(self.user)
        self.assertGreaterEqual(stats["total"], 1)
        self.assertEqual(stats["by_status"].get("interested"), 1)

        keys = await db.acontacted_keys(self.user)
        self.assertIn("id:place1", keys)
        self.assertIn("tel:380441234567", keys)

        self.assertTrue(await db.adelete_note(note_id, self.user))
        self.assertFalse(await db.adelete_note(note_id, self.user))

    async def test_note_of_other_user_is_not_deletable(self):
        note_id = await db.aadd_note(777, "Foreign", "", "called", "")
        self.assertFalse(await db.adelete_note(note_id, self.user))

    async def test_leads_roundtrip(self):
        leads = [{"name": "A", "place_id": "p1", "score": 70},
                 {"name": "B", "place_id": "p2", "score": 50}]
        ids = await db.asave_leads(self.user, "cafe in Lviv", leads)
        self.assertEqual(len(ids), 2)

        stored = await db.aget_lead(ids[0], self.user)
        self.assertEqual(stored["name"], "A")
        self.assertEqual(stored["lead_id"], ids[0])

        self.assertIsNone(await db.aget_lead(ids[0], 999))  # чужий лід недоступний

        last = await db.alast_search_leads(self.user)
        self.assertEqual({item["name"] for item in last}, {"A", "B"})

    async def test_reminders(self):
        note_id = await db.aadd_note(self.user, "Call me", "", "callback", "")
        when = datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertTrue(await db.aset_reminder(note_id, self.user, when))

        pending = await db.apending_reminders()
        self.assertTrue(any(n["id"] == note_id for n in pending))

        await db.amark_reminded(note_id)
        pending_after = await db.apending_reminders()
        self.assertFalse(any(n["id"] == note_id for n in pending_after))

    async def test_cache(self):
        await db.acache_put("key-1", [{"id": "x"}])
        self.assertEqual(await db.acache_get("key-1"), [{"id": "x"}])
        self.assertIsNone(await db.acache_get("missing"))


class SearchPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.ainit_db()
        self.original_page = places._search_page
        self.original_key = places.GOOGLE_API_KEY
        places.GOOGLE_API_KEY = "test-key"
        self.calls = []

    async def asyncTearDown(self):
        places._search_page = self.original_page
        places.GOOGLE_API_KEY = self.original_key

    def _fake_pages(self, pages):
        async def fake(query, page_size, page_token=""):
            self.calls.append((page_size, page_token))
            index = 0 if not page_token else int(page_token)
            items, next_token = pages[index]
            return items, next_token, ""
        return fake

    async def test_pagination_collects_across_pages(self):
        page1 = [{"id": f"p{i}"} for i in range(20)]
        page2 = [{"id": f"q{i}"} for i in range(20)]
        places._search_page = self._fake_pages([(page1, "1"), (page2, "")])
        result, error = await places.search_places("cafe in Lviv unique-1", 35)
        self.assertEqual(error, "")
        self.assertEqual(len(result), 35)
        self.assertEqual(len(self.calls), 2)

    async def test_duplicates_removed(self):
        page1 = [{"id": "same"}, {"id": "other"}]
        page2 = [{"id": "same"}, {"id": "third"}]
        places._search_page = self._fake_pages([(page1, "1"), (page2, "")])
        result, _ = await places.search_places("cafe in Lviv unique-2", 10)
        self.assertEqual([p["id"] for p in result], ["same", "other", "third"])

    async def test_results_are_cached(self):
        places._search_page = self._fake_pages([([{"id": "cached"}], "")])
        first, _ = await places.search_places("cafe in Lviv unique-3", 5)
        calls_after_first = len(self.calls)
        second, _ = await places.search_places("cafe in Lviv unique-3", 5)
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), calls_after_first)  # другий раз мережі не було

    async def test_missing_key_reports_error(self):
        places.GOOGLE_API_KEY = ""
        result, error = await places.search_places("cafe", 5)
        self.assertEqual(result, [])
        self.assertIn("GOOGLE_API_KEY", error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
