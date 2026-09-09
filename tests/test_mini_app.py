import hashlib
import hmac
import json
import time
import unittest
import asyncio
import tempfile
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import quote

from bot.mini_app import MiniApp, validate_init_data
from bot.mini_app import access_state
from bot.database import Database


class InitDataValidationTests(unittest.TestCase):
    def make_init_data(self, token="123:TEST", user_id=42):
        fields = {
            "auth_date": str(int(time.time())),
            "query_id": "AAE",
            "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
        }
        check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return "&".join(f"{quote(k)}={quote(v)}" for k, v in fields.items())

    def test_valid_signature_returns_user(self):
        self.assertEqual(validate_init_data(self.make_init_data(), "123:TEST")["id"], 42)

    def test_tampered_signature_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_init_data(self.make_init_data().replace("Test", "Evil"), "123:TEST")


class MiniAppSchemaTests(unittest.TestCase):
    def test_schema_is_created_without_seed_content(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                db = Database(f"{directory}/mini.db")
                await db.init()
                async with db.connect() as conn:
                    cursor = await conn.execute("SELECT COUNT(*) FROM mini_app_categories")
                    self.assertEqual((await cursor.fetchone())[0], 0)
                    cursor = await conn.execute("SELECT COUNT(*) FROM mini_app_materials")
                    self.assertEqual((await cursor.fetchone())[0], 0)
                    for table in (
                        "mini_app_course_test_attempts",
                        "mini_app_course_feedback",
                        "mini_app_course_assignment_submissions",
                        "mini_app_admin_revisions",
                    ):
                        cursor = await conn.execute(
                            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                            (table,),
                        )
                        self.assertEqual((await cursor.fetchone())[0], 1)
        asyncio.run(check())


class PilotAccessTests(unittest.TestCase):
    def test_access_state_still_uses_existing_membership_rules(self):
        self.assertEqual(access_state(None), "new")


class OwnerTestModeTests(unittest.TestCase):
    def test_owner_can_preview_new_user_without_writing_progress(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database = Database(f"{directory}/mini.db")
                await database.init()
                await database.upsert_user(42, "owner", "Owner")
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    await conn.execute(
                        "UPDATE users SET current_status='active',is_lifetime_free=1 WHERE telegram_id=42"
                    )
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,is_free,status,sort_order,created_at,updated_at
                           ) VALUES(?,1,'published',0,?,?)""",
                        ("Бесплатный материал", stamp, stamp),
                    )
                    material_id = int(cursor.lastrowid)
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_courses(
                               title,status,sort_order,created_at,updated_at
                           ) VALUES(?,'published',0,?,?)""",
                        ("Тестовый курс", stamp, stamp),
                    )
                    course_id = int(cursor.lastrowid)
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_course_units(
                               course_id,title,is_required,sort_order,created_at,updated_at
                           ) VALUES(?,?,1,0,?,?)""",
                        (course_id, "Урок", stamp, stamp),
                    )
                    lesson_id = int(cursor.lastrowid)
                    await conn.commit()

                mini_app = MiniApp(database, "123:TEST", {42}, {42})
                init_data = InitDataValidationTests().make_init_data
                headers = {
                    "X-Telegram-Init-Data": init_data(),
                    "X-Nastaunik-Test-Mode": "1",
                }
                request = SimpleNamespace(headers=headers, query={}, match_info={"material_id": str(material_id)})
                _, _, user = await mini_app.authorised(request)
                self.assertEqual(user["state"], "new")
                self.assertTrue(user["test_mode_available"])
                self.assertEqual(user["test_mode"], "unpaid")
                self.assertIsNone(user["access_end_at"])
                unpaid_payload = json.loads((await mini_app.bootstrap(request)).text)
                self.assertEqual(unpaid_payload["courses"], [])

                material = json.loads((await mini_app.material(request)).text)
                self.assertFalse(material["viewed"])
                await mini_app.material_complete(request)
                await mini_app.material_like(request)
                async with database.connect() as conn:
                    view_count = (await (await conn.execute("SELECT COUNT(*) FROM mini_app_material_views")).fetchone())[0]
                    like_count = (await (await conn.execute("SELECT COUNT(*) FROM mini_app_material_likes")).fetchone())[0]
                self.assertEqual(view_count, 0)
                self.assertEqual(like_count, 0)

                paid_request = SimpleNamespace(
                    headers={
                        "X-Telegram-Init-Data": init_data(),
                        "X-Nastaunik-Test-Mode": "paid",
                    },
                    query={},
                )
                _, _, paid_user = await mini_app.authorised(paid_request)
                self.assertEqual(paid_user["test_mode"], "paid")
                self.assertEqual(paid_user["state"], "active")
                self.assertTrue(paid_user["is_lifetime_free"])
                self.assertIsNone(paid_user["access_end_at"])
                paid_payload = json.loads((await mini_app.bootstrap(paid_request)).text)
                self.assertEqual(len(paid_payload["courses"]), 1)
                self.assertEqual(paid_payload["courses"][0]["title"], "Тестовый курс")

                paid_course_request = SimpleNamespace(
                    headers=paid_request.headers,
                    query={},
                    match_info={"course_id": str(course_id), "lesson_id": str(lesson_id)},
                )
                lesson = json.loads((await mini_app.course_lesson(paid_course_request)).text)
                self.assertEqual(lesson["title"], "Урок")
                completion = json.loads((await mini_app.course_lesson_complete(paid_course_request)).text)
                self.assertEqual(completion["test_mode"], "paid")
                preview = await mini_app.preview(SimpleNamespace(query={
                    "course": str(course_id),
                    "mode": "paid",
                }))
                self.assertIn("window.NASTAUNIK_PREVIEW=", preview.text)
                self.assertIn("Тестовый курс", preview.text)
                self.assertIn(f'"courseId": {course_id}', preview.text)
                unpaid_preview = await mini_app.preview(SimpleNamespace(query={
                    "course": str(course_id),
                    "mode": "unpaid",
                }))
                self.assertIn('"state": "new"', unpaid_preview.text)
                async with database.connect() as conn:
                    course_progress = (await (await conn.execute(
                        "SELECT COUNT(*) FROM mini_app_course_unit_progress"
                    )).fetchone())[0]
                    course_state = (await (await conn.execute(
                        "SELECT COUNT(*) FROM mini_app_course_user_state"
                    )).fetchone())[0]
                self.assertEqual(course_progress, 0)
                self.assertEqual(course_state, 0)

                outsider_request = SimpleNamespace(
                    headers={
                        "X-Telegram-Init-Data": init_data(user_id=43),
                        "X-Nastaunik-Test-Mode": "1",
                    },
                    query={},
                )
                _, _, outsider = await mini_app.authorised(outsider_request)
                self.assertFalse(outsider["test_mode_available"])
                self.assertFalse(outsider["test_mode"])

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
