import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from bot.database import Database
from bot.learning import complete_material, get_bootstrap, get_catalog, get_material, toggle_material_like
from bot.learning_admin_v2 import LearningAdmin, clean_rich_text


class LearningCatalogCardTests(unittest.TestCase):
    def test_catalog_includes_neutral_tag_data_and_automatic_preview(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                database = Database(database_path)
                await database.init()
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,full_description,status,sort_order,created_at,updated_at
                           ) VALUES(?,?,'published',0,?,?)""",
                        (
                            "Материал",
                            '<video src="/mini-app/media/first.mp4"></video><img src="/mini-app/media/article.jpg">',
                            stamp,
                            stamp,
                        ),
                    )
                    material_id = cursor.lastrowid
                    cursor = await conn.execute(
                        "INSERT INTO mini_app_tags(name,slug,color,created_at,updated_at) VALUES(?,?,?,?,?)",
                        ("Практика", "practice", "#ff0000", stamp, stamp),
                    )
                    await conn.execute(
                        "INSERT INTO mini_app_material_tags(material_id,tag_id) VALUES(?,?)",
                        (material_id, cursor.lastrowid),
                    )
                    await conn.commit()

                catalog = await get_catalog(database)
                material = catalog["materials"][0]
                self.assertEqual(material["preview_url"], "/mini-app/media/article.jpg")
                self.assertEqual(material["preview_kind"], "image")
                self.assertEqual(material["tags"][0]["name"], "Практика")
                self.assertNotIn("color", material["tags"][0])
                self.assertNotIn("full_description", material)
                self.assertEqual(catalog["tags"][0]["name"], "Практика")

        asyncio.run(check())

    def test_guest_catalog_marks_only_paid_materials_as_locked(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                database = Database(database_path)
                await database.init()
                await database.upsert_user(51, "guest", "Guest")
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    await conn.executemany(
                        """INSERT INTO mini_app_materials(
                               title,full_description,is_free,status,sort_order,created_at,updated_at
                           ) VALUES(?,?,?,'published',0,?,?)""",
                        [
                            ("Бесплатный", '<img src="/mini-app/media/free.jpg">', 1, stamp, stamp),
                            ("Для клуба", '<video src="/mini-app/media/paid.mp4"></video>', 0, stamp, stamp),
                        ],
                    )
                    await conn.commit()

                payload = await get_bootstrap(database, {"telegram_id": 51, "state": "new"})
                materials = {item["title"]: item for item in payload["materials"]}
                self.assertFalse(materials["Бесплатный"]["locked"])
                self.assertEqual(materials["Бесплатный"]["preview_url"], "/mini-app/media/free.jpg")
                self.assertTrue(materials["Для клуба"]["locked"])
                self.assertIsNone(materials["Для клуба"]["preview_url"])
                self.assertNotIn("full_description", materials["Для клуба"])

        asyncio.run(check())

    def test_catalog_uses_video_when_no_image_exists(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                database = Database(database_path)
                await database.init()
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,status,sort_order,created_at,updated_at
                           ) VALUES(?,'published',0,?,?)""",
                        ("Видео", stamp, stamp),
                    )
                    await conn.execute(
                        """INSERT INTO mini_app_material_blocks(
                               material_id,block_type,content,sort_order,created_at
                           ) VALUES(?,'video',?,0,?)""",
                        (cursor.lastrowid, "/mini-app/media/lesson.mp4", stamp),
                    )
                    await conn.execute(
                        """INSERT INTO mini_app_video_jobs(
                               stored_name,status,original_size,poster_name,created_at,updated_at
                           ) VALUES(?,'ready',100,?,?,?)""",
                        ("lesson.mp4", "lesson.poster.webp", stamp, stamp),
                    )
                    await conn.commit()

                material = (await get_catalog(database))["materials"][0]
                self.assertEqual(material["preview_url"], "/mini-app/media/lesson.mp4")
                self.assertEqual(material["preview_kind"], "video")
                self.assertEqual(material["preview_poster_url"], "/mini-app/media/lesson.poster.webp")

        asyncio.run(check())

    def test_rich_text_sanitizer_keeps_formatting_and_removes_unsafe_markup(self):
        cleaned = clean_rich_text(
            '<script>alert(1)</script><h2 style="color:red">Заголовок</h2>'
            '<a href="javascript:alert(1)" onclick="x()">ссылка</a>'
            '<figure class="inline-media other" draggable="true"><img src="/mini-app/media/a.jpg" onerror="x()">'
            '<figcaption contenteditable="true">Подпись</figcaption></figure>'
        )
        self.assertNotIn("alert", cleaned)
        self.assertNotIn("onclick", cleaned)
        self.assertNotIn("onerror", cleaned)
        self.assertNotIn("style=", cleaned)
        self.assertIn("<h2>Заголовок</h2>", cleaned)
        self.assertIn('class="inline-media"', cleaned)
        self.assertIn('src="/mini-app/media/a.jpg"', cleaned)

    def test_cleanup_only_removes_old_unreferenced_uploads(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database_path = root / "mini.db"
                media_dir = root / "media"
                media_dir.mkdir()
                database = Database(database_path)
                await database.init()
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                old_stamp = (datetime.utcnow() - timedelta(days=2)).isoformat(timespec="seconds")
                names = ["content-referenced.jpg", "content-orphan.jpg", "content-recent.jpg", "content-active.mp4", "content-abandoned.mp4"]
                for name in names:
                    (media_dir / name).write_bytes(b"test")
                old_time = (datetime.utcnow() - timedelta(days=2)).timestamp()
                for name in names:
                    if name != "content-recent.jpg":
                        os.utime(media_dir / name, (old_time, old_time))
                async with database.connect() as conn:
                    await conn.execute(
                        """INSERT INTO mini_app_materials(title,full_description,status,sort_order,created_at,updated_at)
                           VALUES(?,?,'published',0,?,?)""",
                        ("Сохранённый", '<img src="/mini-app/media/content-referenced.jpg">', stamp, stamp),
                    )
                    await conn.executemany(
                        """INSERT INTO mini_app_video_jobs(stored_name,status,original_size,created_at,updated_at)
                           VALUES(?,?,?,?,?)""",
                        [
                            ("content-active.mp4", "queued", 4, old_stamp, old_stamp),
                            ("content-abandoned.mp4", "waiting_save", 4, old_stamp, old_stamp),
                        ],
                    )
                    await conn.commit()
                admin = LearningAdmin(database_path, lambda path, **query: path)
                admin.media_dir = media_dir
                removed = await admin.cleanup_orphan_uploads()
                self.assertEqual(removed, 2)
                self.assertTrue((media_dir / "content-referenced.jpg").exists())
                self.assertTrue((media_dir / "content-recent.jpg").exists())
                self.assertTrue((media_dir / "content-active.mp4").exists())
                self.assertFalse((media_dir / "content-orphan.jpg").exists())
                self.assertFalse((media_dir / "content-abandoned.mp4").exists())

        asyncio.run(check())

    def test_backfill_creates_job_for_existing_referenced_video(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database_path = root / "mini.db"
                media_dir = root / "media"
                media_dir.mkdir()
                video = media_dir / "content-existing.mp4"
                video.write_bytes(b"existing video")
                database = Database(database_path)
                await database.init()
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    await conn.execute(
                        """INSERT INTO mini_app_materials(title,full_description,status,sort_order,created_at,updated_at)
                           VALUES(?,?,'published',0,?,?)""",
                        ("Видео", '<video src="/mini-app/media/content-existing.mp4"></video>', stamp, stamp),
                    )
                    await conn.commit()
                admin = LearningAdmin(database_path, lambda path, **query: path)
                admin.media_dir = media_dir

                async def fake_poster(target):
                    poster = target.with_name(f"{target.stem}.poster.webp")
                    poster.write_bytes(b"poster")
                    return poster.name

                admin.create_video_poster = fake_poster
                self.assertEqual(await admin.backfill_video_posters(), 1)
                async with database.connect() as conn:
                    row = await (await conn.execute(
                        "SELECT status,poster_name FROM mini_app_video_jobs WHERE stored_name=?",
                        (video.name,),
                    )).fetchone()
                self.assertEqual(row["status"], "ready")
                self.assertEqual(row["poster_name"], "content-existing.poster.webp")

        asyncio.run(check())

    def test_views_completion_and_likes_are_unique_per_user(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                database = Database(database_path)
                await database.init()
                await database.upsert_user(42, "reader", "Reader")
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,status,sort_order,created_at,updated_at
                           ) VALUES(?,'published',0,?,?)""",
                        ("Статья", stamp, stamp),
                    )
                    material_id = cursor.lastrowid
                    await conn.commit()

                opened = await get_material(database, material_id, 42)
                self.assertEqual(opened["view_count"], 1)
                self.assertFalse(opened["viewed"])
                self.assertEqual((await get_material(database, material_id, 42))["view_count"], 1)

                completed = await complete_material(database, material_id, 42)
                self.assertTrue(completed["viewed"])
                catalog_item = (await get_catalog(database, telegram_id=42))["materials"][0]
                self.assertTrue(catalog_item["viewed"])

                liked = await toggle_material_like(database, material_id, 42)
                self.assertTrue(liked["liked"])
                self.assertEqual(liked["like_count"], 1)
                unliked = await toggle_material_like(database, material_id, 42)
                self.assertFalse(unliked["liked"])
                self.assertEqual(unliked["like_count"], 0)

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
