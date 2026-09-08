import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from multidict import MultiDict

from bot.database import Database
from bot.learning_admin_v2 import LearningAdmin


class CourseAdminBuilderTests(unittest.TestCase):
    def test_course_can_have_optional_modules_lessons_and_blocks(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                await Database(database_path).init()
                admin = LearningAdmin(database_path, lambda path, **query: path)

                with self.assertRaises(web.HTTPSeeOther) as longread_redirect:
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_save"),
                        ("title", "Новый курс"),
                        ("description", "Описание"),
                    ]))
                async with Database(database_path).connect() as db:
                    course = await (await db.execute("SELECT * FROM mini_app_courses")).fetchone()
                self.assertEqual(course["title"], "Новый курс")
                self.assertEqual(course["status"], "draft")

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_save"),
                        ("course_id", str(course["id"])),
                        ("title", "Новый курс"),
                        ("description", "Описание"),
                        ("is_visible", "1"),
                    ]))
                async with Database(database_path).connect() as db:
                    course = await (await db.execute("SELECT * FROM mini_app_courses")).fetchone()
                self.assertEqual(course["status"], "published")
                self.assertEqual(course["is_visible"], 1)

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_module_add"),
                        ("course_id", str(course["id"])),
                        ("title", "Основы"),
                    ]))
                async with Database(database_path).connect() as db:
                    module = await (await db.execute("SELECT * FROM mini_app_course_modules")).fetchone()

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_lesson_add"),
                        ("course_id", str(course["id"])),
                        ("module_id", str(module["id"])),
                        ("title", "Первый урок"),
                    ]))
                async with Database(database_path).connect() as db:
                    lesson = await (await db.execute("SELECT * FROM mini_app_course_units")).fetchone()
                self.assertEqual(lesson["module_id"], module["id"])

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_module_add"),
                        ("course_id", str(course["id"])),
                        ("title", "Практика"),
                    ]))
                async with Database(database_path).connect() as db:
                    second_module = await (await db.execute(
                        "SELECT * FROM mini_app_course_modules WHERE title='Практика'"
                    )).fetchone()

                move_response = await admin.course_admin.action(None, MultiDict([
                    ("action", "course_tree_move"),
                    ("ajax", "1"),
                    ("course_id", str(course["id"])),
                    ("item_type", "lesson"),
                    ("item_id", str(lesson["id"])),
                    ("target_module_id", str(second_module["id"])),
                ]))
                self.assertEqual(move_response.status, 200)
                async with Database(database_path).connect() as db:
                    moved_lesson = await (await db.execute(
                        "SELECT * FROM mini_app_course_units WHERE id=?", (lesson["id"],)
                    )).fetchone()
                self.assertEqual(moved_lesson["module_id"], second_module["id"])

                admin.media_dir = Path(directory) / "media"
                inline_response = await admin.course_admin.action(None, MultiDict([
                    ("action", "course_inline_upload"),
                    ("course_id", str(course["id"])),
                    ("lesson_id", str(lesson["id"])),
                    ("inline_file", SimpleNamespace(filename="photo.jpg", file=io.BytesIO(b"image"))),
                ]))
                self.assertEqual(inline_response.status, 200)
                self.assertIn('"kind": "image"', inline_response.text)

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_block_add"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("block_type", "longread"),
                        ("content", "<script>bad()</script><p>Текст урока</p>"),
                    ]))
                self.assertEqual(longread_redirect.exception.status, 303)
                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_block_add"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("block_type", "test"),
                        ("content", "Какой ответ правильный?"),
                    ]))
                async with Database(database_path).connect() as db:
                    rows = await (await db.execute(
                        "SELECT id,block_type,content,material_id FROM mini_app_course_blocks ORDER BY sort_order"
                    )).fetchall()
                    course_material = await (await db.execute(
                        "SELECT * FROM mini_app_materials WHERE id=?", (rows[0]["material_id"],)
                    )).fetchone()
                self.assertEqual([row["block_type"] for row in rows], ["longread", "test"])
                self.assertNotIn("script", rows[0]["content"])
                self.assertEqual(course_material["library_visible"], 0)
                self.assertNotIn("script", course_material["full_description"])

                async def course_material_post():
                    return MultiDict([
                        ("action", "material_save"),
                        ("editor", "1"),
                        ("id", str(course_material["id"])),
                        ("title", "Лонгрид урока"),
                        ("full_description", "<p>Текст урока</p>"),
                        ("is_free", "1"),
                        ("course_material", "1"),
                        ("return_course", str(course["id"])),
                        ("return_lesson", str(lesson["id"])),
                        ("return_block", str(rows[0]["id"])),
                    ])

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.action(SimpleNamespace(post=course_material_post))
                async with Database(database_path).connect() as db:
                    protected_course_material = await (await db.execute(
                        "SELECT is_free,library_visible FROM mini_app_materials WHERE id=?",
                        (course_material["id"],),
                    )).fetchone()
                self.assertEqual(protected_course_material["is_free"], 0)
                self.assertEqual(protected_course_material["library_visible"], 0)
                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_module_add"),
                        ("course_id", str(course["id"])),
                    ]))
                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_lesson_add"),
                        ("course_id", str(course["id"])),
                    ]))
                async with Database(database_path).connect() as db:
                    self.assertIsNotNone(await (await db.execute(
                        "SELECT id FROM mini_app_course_modules WHERE title='Модуль 1'"
                    )).fetchone())
                    self.assertIsNotNone(await (await db.execute(
                        "SELECT id FROM mini_app_course_units WHERE title='Урок 1' AND module_id IS NULL"
                    )).fetchone())
                index_html = (await admin.course_admin.index(None)).text
                course_html = (await admin.course_admin.course_editor(SimpleNamespace(query={"course": str(course["id"])}))).text
                lesson_html = (await admin.course_admin.lesson_editor(SimpleNamespace(query={"course": str(course["id"]), "lesson": str(lesson["id"])}))).text
                material_html = (await admin.article_editor(SimpleNamespace(query={
                    "material": str(course_material["id"]),
                    "course_material": "1",
                    "return_course": str(course["id"]),
                    "return_lesson": str(lesson["id"]),
                    "return_block": str(rows[0]["id"]),
                }))).text
                regular_material_html = (await admin.article_editor(SimpleNamespace(query={"material": "new"}))).text
                empty_outline = admin.course_admin.course_outline(
                    {"id": course["id"], "title": course["title"]}, [], [], None
                )
                self.assertIn("Создать курс", index_html)
                self.assertNotIn("Уроки без модулей", course_html)
                self.assertIn('class="course-outline"', course_html)
                self.assertIn("Перетаскивайте уроки и модули", course_html)
                self.assertIn('data-tree-kind="module"', course_html)
                self.assertIn('admin_uploads.js?v=2', course_html)
                self.assertIn('data-upload-label="Обложка курса"', course_html)
                self.assertNotIn("Результат обучения", course_html)
                self.assertNotIn("Продолжительность", course_html)
                self.assertNotIn('name="outcome"', course_html)
                self.assertNotIn('name="duration_label"', course_html)
                self.assertIn('name="is_visible" value="1" checked', course_html)
                self.assertNotIn('type="checkbox" disabled', course_html)
                self.assertIn("Опубликовать курс в Mini App", course_html)
                self.assertIn('tree-lesson active', lesson_html)
                self.assertIn('admin_uploads.js?v=2', lesson_html)
                self.assertIn('data-upload-label="Видео урока"', lesson_html)
                self.assertIn('data-upload-label="Изображение урока"', lesson_html)
                self.assertIn("Открыть редактор лонгрида", lesson_html)
                self.assertIn('data-add-form="video"', lesson_html)
                self.assertLess(lesson_html.index("Добавить в урок"), lesson_html.index('class="lesson-blocks"'))
                self.assertLess(lesson_html.index('class="lesson-blocks"'), lesson_html.index("Открыть редактор лонгрида"))
                self.assertIn('class="tree-delete"', lesson_html)
                self.assertIn("Вернуться к уроку", material_html)
                self.assertIn("Материал урока", material_html)
                self.assertIn("Этот лонгрид является частью курса", material_html)
                self.assertIn("О чём этот лонгрид", material_html)
                self.assertIn('admin_uploads.js?v=2', material_html)
                self.assertIn('data-upload-label="Медиа лонгрида"', material_html)
                self.assertNotIn('name="is_free"', material_html)
                self.assertNotIn("<h2>Теги</h2>", material_html)
                self.assertNotIn("<h2>Обложка</h2>", material_html)
                self.assertNotIn("<h2>Дополнительные материалы</h2>", material_html)
                self.assertIn('name="is_free"', regular_material_html)
                self.assertIn("<h2>Теги</h2>", regular_material_html)
                self.assertIn("<h2>Обложка</h2>", regular_material_html)
                self.assertIn("<h2>Дополнительные материалы</h2>", regular_material_html)
                self.assertNotIn("Без модуля", empty_outline)
                self.assertNotIn(">Модули<", empty_outline)
                self.assertNotIn("Модулей пока нет", empty_outline)
                self.assertIn("Лонгрид", lesson_html)
                self.assertIn("Тест", lesson_html)
                upload_script = (Path(__file__).resolve().parents[1] / "mini_app" / "static" / "admin_uploads.js").read_text(encoding="utf-8")
                self.assertNotIn("upload(form.action", upload_script)
                self.assertEqual(upload_script.count("form.getAttribute('action') || window.location.href"), 2)
                course_script = (Path(__file__).resolve().parents[1] / "mini_app" / "static" / "admin_course.js").read_text(encoding="utf-8")
                material_script = (Path(__file__).resolve().parents[1] / "mini_app" / "static" / "admin_material.js").read_text(encoding="utf-8")
                self.assertNotIn("form.action", course_script)
                self.assertNotIn("form.action", material_script)

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
