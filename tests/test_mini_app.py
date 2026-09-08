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
                self.assertTrue(user["test_mode"])
                self.assertIsNone(user["access_end_at"])

                material = json.loads((await mini_app.material(request)).text)
                self.assertFalse(material["viewed"])
                await mini_app.material_complete(request)
                await mini_app.material_like(request)
                async with database.connect() as conn:
                    view_count = (await (await conn.execute("SELECT COUNT(*) FROM mini_app_material_views")).fetchone())[0]
                    like_count = (await (await conn.execute("SELECT COUNT(*) FROM mini_app_material_likes")).fetchone())[0]
                self.assertEqual(view_count, 0)
                self.assertEqual(like_count, 0)

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
