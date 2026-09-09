import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from multidict import MultiDict

from bot.database import Database
from bot.learning_admin_v2 import LearningAdmin


class CourseAdminBuilderTests(unittest.TestCase):
    def test_autosave_history_and_restore(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                database_path = Path(directory) / "mini.db"
                await Database(database_path).init()
                admin = LearningAdmin(database_path, lambda path, **query: path)

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_save"),
                        ("title", "Первая версия"),
                        ("description", "Исходное описание"),
                        ("is_visible", "1"),
                    ]))
                async with Database(database_path).connect() as db:
                    course = await (await db.execute("SELECT id FROM mini_app_courses")).fetchone()

                response = await admin.course_admin.action(None, MultiDict([
                    ("action", "course_save"),
                    ("ajax", "1"),
                    ("autosave", "1"),
                    ("course_id", str(course["id"])),
                    ("title", "Вторая версия"),
                    ("description", "Сохранено автоматически"),
                    ("is_visible", "1"),
                ]))
                self.assertEqual(response.status, 200)
                async with Database(database_path).connect() as db:
                    revisions = await (await db.execute(
                        "SELECT id,snapshot_json FROM mini_app_admin_revisions WHERE entity_type='course' AND entity_id=? ORDER BY id",
                        (course["id"],),
                    )).fetchall()
                self.assertGreaterEqual(len(revisions), 2)
                first_revision_id = next(
                    row["id"] for row in revisions
                    if json.loads(row["snapshot_json"])["title"] == "Первая версия"
                )

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_revision_restore"),
                        ("course_id", str(course["id"])),
                        ("revision_id", str(first_revision_id)),
                    ]))
                async with Database(database_path).connect() as db:
                    restored = await (await db.execute(
                        "SELECT title,description FROM mini_app_courses WHERE id=?", (course["id"],)
                    )).fetchone()
                    restore_entry = await (await db.execute(
                        "SELECT source FROM mini_app_admin_revisions WHERE entity_type='course' AND entity_id=? ORDER BY id DESC LIMIT 1",
                        (course["id"],),
                    )).fetchone()
                self.assertEqual(restored["title"], "Первая версия")
                self.assertEqual(restored["description"], "Исходное описание")
                self.assertEqual(restore_entry["source"], "restore")

                async def create_material():
                    return MultiDict([
                        ("action", "material_save"),
                        ("editor", "1"),
                        ("title", "Материал — версия 1"),
                        ("full_description", "<p>Первый текст</p>"),
                    ])

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.action(SimpleNamespace(post=create_material))
                async with Database(database_path).connect() as db:
                    material = await (await db.execute("SELECT id FROM mini_app_materials")).fetchone()

                async def autosave_material():
                    return MultiDict([
                        ("action", "material_save"),
                        ("editor", "1"),
                        ("ajax", "1"),
                        ("autosave", "1"),
                        ("id", str(material["id"])),
                        ("title", "Материал — версия 2"),
                        ("full_description", "<p>Второй текст</p>"),
                    ])

                material_response = await admin.action(SimpleNamespace(post=autosave_material))
                self.assertEqual(material_response.status, 200)
                material_html = (await admin.article_editor(SimpleNamespace(query={"material": str(material["id"])}))).text
                self.assertIn("История изменений", material_html)
                self.assertIn("Автосохранение", material_html)
                self.assertIn("admin_autosave.js", material_html)

        asyncio.run(check())

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
                        ("sequential_access", "1"),
                        ("completion_title", "Вы справились"),
                        ("completion_text", "Курс завершён"),
                        ("completion_recommendation", "Переходите дальше"),
                        ("is_visible", "1"),
                    ]))
                async with Database(database_path).connect() as db:
                    course = await (await db.execute("SELECT * FROM mini_app_courses")).fetchone()
                self.assertEqual(course["status"], "published")
                self.assertEqual(course["is_visible"], 1)
                self.assertEqual(course["sequential_access"], 1)
                self.assertEqual(course["completion_title"], "Вы справились")

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
                        ("action", "course_lesson_save"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("module_id", str(module["id"])),
                        ("title", "Первый урок"),
                        ("description", "Описание урока"),
                        ("is_required", "1"),
                        ("previous_button_label", "Вернуться назад"),
                        ("next_button_label", "Перейти к практике"),
                        ("finish_button_label", "Закончить обучение"),
                    ]))
                async with Database(database_path).connect() as db:
                    saved_lesson = await (await db.execute(
                        "SELECT * FROM mini_app_course_units WHERE id=?", (lesson["id"],)
                    )).fetchone()
                self.assertEqual(saved_lesson["previous_button_label"], "Вернуться назад")
                self.assertEqual(saved_lesson["next_button_label"], "Перейти к практике")
                self.assertEqual(saved_lesson["finish_button_label"], "Закончить обучение")

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

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_block_save"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("block_id", str(rows[1]["id"])),
                        ("content", "Какой ответ правильный?"),
                        ("option_0", "Да"),
                        ("option_1", "Нет"),
                        ("correct_option", "0"),
                        ("explanation", "Да — правильный ответ"),
                    ]))
                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_block_add"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("block_type", "file"),
                        ("title", "Чек-лист"),
                        ("description", "Скачайте перед уроком"),
                        ("block_file", SimpleNamespace(filename="checklist.pdf", file=io.BytesIO(b"pdf"))),
                    ]))
                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_block_add"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("block_type", "assignment"),
                        ("title", "Практика"),
                        ("content", "Пришлите ссылку"),
                        ("response_type", "link"),
                    ]))
                async with Database(database_path).connect() as db:
                    block_rows = await (await db.execute(
                        "SELECT block_type,title,settings_json FROM mini_app_course_blocks ORDER BY sort_order"
                    )).fetchall()
                self.assertEqual([row["block_type"] for row in block_rows], ["longread", "test", "file", "assignment"])
                self.assertIn("правильный ответ", block_rows[1]["settings_json"])
                self.assertEqual(block_rows[2]["title"], "Чек-лист")
                self.assertIn('"response_type": "link"', block_rows[3]["settings_json"])

                await Database(database_path).upsert_user(77, "student", "Тестовый участник")
                async with Database(database_path).connect() as db:
                    cursor = await db.execute(
                        """INSERT INTO mini_app_course_feedback(
                               telegram_id,course_id,review_text,review_status,created_at,updated_at
                           ) VALUES(?,?,?,'pending',datetime('now'),datetime('now'))""",
                        (77, course["id"], "Очень полезный курс"),
                    )
                    feedback_id = int(cursor.lastrowid)
                    await db.commit()
                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_review_moderate"),
                        ("course_id", str(course["id"])),
                        ("feedback_id", str(feedback_id)),
                        ("review_status", "approved"),
                    ]))
                async with Database(database_path).connect() as db:
                    moderated = await (await db.execute(
                        "SELECT review_status FROM mini_app_course_feedback WHERE id=?",
                        (feedback_id,),
                    )).fetchone()
                self.assertEqual(moderated["review_status"], "approved")

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
                self.assertIn("Кнопки перехода", lesson_html)
                self.assertIn("Перейти к практике", lesson_html)
                self.assertIn("Последовательное прохождение", course_html)
                self.assertIn("Аналитика курса", course_html)
                self.assertIn("Как оплаченный", course_html)
                self.assertIn("Отзывы и модерация", course_html)
                self.assertIn("Дополнительный файл", lesson_html)
                self.assertIn("Задание", lesson_html)
                self.assertIn("Перетаскивайте уроки и модули", course_html)
                self.assertIn('data-tree-kind="module"', course_html)
                self.assertIn('admin_uploads.js?v=3', course_html)
                self.assertIn('data-upload-label="Обложка курса"', course_html)
                self.assertNotIn("Результат обучения", course_html)
                self.assertNotIn("Продолжительность", course_html)
                self.assertNotIn('name="outcome"', course_html)
                self.assertNotIn('name="duration_label"', course_html)
                self.assertIn('name="is_visible" value="1" checked', course_html)
                self.assertNotIn('type="checkbox" disabled', course_html)
                self.assertIn("Опубликовать курс в Mini App", course_html)
                self.assertIn('tree-lesson active', lesson_html)
                self.assertIn('admin_uploads.js?v=3', lesson_html)
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
                self.assertIn('admin_uploads.js?v=3', material_html)
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
