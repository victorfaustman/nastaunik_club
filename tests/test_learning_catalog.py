import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from bot.database import Database
from bot.learning import (
    complete_course_lesson,
    complete_material,
    get_bootstrap,
    get_catalog,
    get_course,
    get_course_lesson,
    get_material,
    toggle_material_like,
)
from bot.learning_admin_v2 import LearningAdmin, clean_rich_text
from bot.media_embed import youtube_video_id


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
                    await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,full_description,library_visible,status,sort_order,created_at,updated_at
                           ) VALUES(?,?,0,'published',0,?,?)""",
                        ("Лонгрид курса", "Не показывать в библиотеке", stamp, stamp),
                    )
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
                self.assertEqual(len(catalog["materials"]), 1)
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

    def test_catalog_uses_youtube_thumbnail_when_article_has_no_image(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                database = Database(database_path)
                await database.init()
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,full_description,status,sort_order,created_at,updated_at
                           ) VALUES(?,?,'published',0,?,?)""",
                        (
                            "YouTube",
                            '<figure class="inline-media"><iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe></figure>',
                            stamp,
                            stamp,
                        ),
                    )
                    await conn.commit()

                material = (await get_catalog(database))["materials"][0]
                self.assertEqual(material["preview_url"], "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
                self.assertEqual(material["preview_kind"], "image")

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
        self.assertNotIn(
            "Добавьте подпись",
            clean_rich_text('<figure><img src="/mini-app/media/a.jpg"><figcaption contenteditable="true">Добавьте подпись</figcaption></figure>'),
        )

    def test_rich_text_sanitizer_keeps_only_safe_youtube_embeds(self):
        cleaned = clean_rich_text(
            '<iframe src="https://www.youtube.com/watch?v=dQw4w9WgXcQ" onload="bad()"></iframe>'
            '<iframe src="https://evil.example/embed/dQw4w9WgXcQ"></iframe>'
        )
        self.assertIn('src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"', cleaned)
        self.assertIn("allowfullscreen", cleaned)
        self.assertNotIn("onload", cleaned)
        self.assertNotIn("evil.example", cleaned)

    def test_youtube_url_parser_supports_common_link_shapes(self):
        expected = "dQw4w9WgXcQ"
        self.assertEqual(youtube_video_id(f"https://youtu.be/{expected}?si=test"), expected)
        self.assertEqual(youtube_video_id(f"https://www.youtube.com/watch?v={expected}&t=10"), expected)
        self.assertEqual(youtube_video_id(f"https://youtube.com/shorts/{expected}"), expected)
        self.assertIsNone(youtube_video_id("https://example.com/watch?v=dQw4w9WgXcQ"))

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

    def test_course_flow_resumes_and_completes_required_lessons(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                database = Database(database_path)
                await database.init()
                await database.upsert_user(42, "student", "Student")
                stamp = datetime.utcnow().isoformat(timespec="seconds")
                async with database.connect() as conn:
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_courses(title,description,status,sort_order,created_at,updated_at)
                           VALUES(?,?,'published',0,?,?)""",
                        ("Практический курс", "Описание", stamp, stamp),
                    )
                    course_id = int(cursor.lastrowid)
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_course_modules(course_id,title,sort_order,created_at,updated_at)
                           VALUES(?,?,0,?,?)""",
                        (course_id, "Основы", stamp, stamp),
                    )
                    module_id = int(cursor.lastrowid)
                    lesson_ids = []
                    for order, (title, required) in enumerate(
                        [("Первый урок", 1), ("Дополнительный урок", 0), ("Финальный урок", 1)]
                    ):
                        cursor = await conn.execute(
                            """INSERT INTO mini_app_course_units(
                                   course_id,module_id,title,is_required,sort_order,created_at,updated_at
                               ) VALUES(?,?,?,?,?,?,?)""",
                            (course_id, module_id, title, required, order, stamp, stamp),
                        )
                        lesson_ids.append(int(cursor.lastrowid))
                    cursor = await conn.execute(
                        """INSERT INTO mini_app_materials(
                               title,short_description,full_description,library_visible,status,sort_order,created_at,updated_at
                           ) VALUES(?,?,?,0,'published',0,?,?)""",
                        ("Лонгрид урока", "Введение", "<p>Текст урока</p>", stamp, stamp),
                    )
                    material_id = int(cursor.lastrowid)
                    await conn.execute(
                        """INSERT INTO mini_app_course_blocks(
                               lesson_id,block_type,material_id,sort_order,created_at,updated_at
                           ) VALUES(?,'longread',?,0,?,?)""",
                        (lesson_ids[0], material_id, stamp, stamp),
                    )
                    await conn.execute(
                        """INSERT INTO mini_app_course_blocks(
                               lesson_id,block_type,content,settings_json,sort_order,created_at,updated_at
                           ) VALUES(?,'test',?,?,0,?,?)""",
                        (
                            lesson_ids[2],
                            "Главный вопрос",
                            '{"options":["Первый","Второй"],"correct":0}',
                            stamp,
                            stamp,
                        ),
                    )
                    await conn.commit()

                payload = await get_bootstrap(database, {"telegram_id": 42, "state": "active"})
                summary = payload["courses"][0]
                self.assertEqual(summary["lesson_count"], 3)
                self.assertEqual(summary["required_count"], 2)
                self.assertEqual(summary["progress"], 0)
                self.assertFalse(summary["started"])
                self.assertEqual(summary["resume_lesson_id"], lesson_ids[0])

                lesson = await get_course_lesson(database, course_id, lesson_ids[0], 42)
                self.assertEqual(lesson["position"], 1)
                self.assertEqual(lesson["next_lesson_id"], lesson_ids[1])
                self.assertEqual(lesson["blocks"][0]["content"], "<p>Текст урока</p>")
                opened_course = await get_course(database, course_id, 42)
                self.assertTrue(opened_course["started"])
                self.assertEqual(opened_course["resume_lesson_id"], lesson_ids[0])

                first = await complete_course_lesson(database, course_id, lesson_ids[0], 42)
                self.assertEqual(first["progress"], 50)
                self.assertEqual(first["next_lesson_id"], lesson_ids[1])
                self.assertFalse(first["completed"])

                optional = await complete_course_lesson(database, course_id, lesson_ids[1], 42)
                self.assertEqual(optional["progress"], 50)
                self.assertEqual(optional["next_lesson_id"], lesson_ids[2])

                final = await complete_course_lesson(database, course_id, lesson_ids[2], 42)
                self.assertEqual(final["progress"], 100)
                self.assertTrue(final["completed"])
                self.assertTrue(final["is_last"])
                completed_course = await get_course(database, course_id, 42)
                self.assertTrue(completed_course["completed"])
                self.assertEqual(completed_course["resume_lesson_id"], lesson_ids[0])
                self.assertTrue(all(item["completed"] for item in completed_course["lessons"]))

                async with database.connect() as conn:
                    state_row = await (await conn.execute(
                        "SELECT * FROM mini_app_course_user_state WHERE telegram_id=? AND course_id=?",
                        (42, course_id),
                    )).fetchone()
                self.assertEqual(state_row["last_lesson_id"], lesson_ids[2])
                self.assertIsNotNone(state_row["completed_at"])

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
