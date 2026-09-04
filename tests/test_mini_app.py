import hashlib
import hmac
import json
import time
import unittest
import asyncio
import tempfile
from urllib.parse import quote

from bot.mini_app import validate_init_data
from bot.database import Database


class InitDataValidationTests(unittest.TestCase):
    def make_init_data(self, token="123:TEST"):
        fields = {
            "auth_date": str(int(time.time())),
            "query_id": "AAE",
            "user": json.dumps({"id": 42, "first_name": "Test"}, separators=(",", ":")),
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


if __name__ == "__main__":
    unittest.main()
