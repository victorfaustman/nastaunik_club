import asyncio
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

                with self.assertRaises(web.HTTPSeeOther):
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

                with self.assertRaises(web.HTTPSeeOther):
                    await admin.course_admin.action(None, MultiDict([
                        ("action", "course_block_add"),
                        ("course_id", str(course["id"])),
                        ("lesson_id", str(lesson["id"])),
                        ("block_type", "longread"),
                        ("title", "Введение"),
                        ("content", "Текст урока"),
                    ]))
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
                        "SELECT block_type,content FROM mini_app_course_blocks ORDER BY sort_order"
                    )).fetchall()
                self.assertEqual([row["block_type"] for row in rows], ["longread", "test"])
                index_html = (await admin.course_admin.index(None)).text
                course_html = (await admin.course_admin.course_editor(SimpleNamespace(query={"course": str(course["id"])}))).text
                lesson_html = (await admin.course_admin.lesson_editor(SimpleNamespace(query={"course": str(course["id"]), "lesson": str(lesson["id"])}))).text
                self.assertIn("Создать курс", index_html)
                self.assertIn("Уроки без модулей", course_html)
                self.assertIn('class="course-outline"', course_html)
                self.assertIn("Перетаскивайте уроки и модули", course_html)
                self.assertIn('data-tree-kind="module"', course_html)
                self.assertIn('tree-lesson active', lesson_html)
                self.assertIn("Лонгрид", lesson_html)
                self.assertIn("Тест", lesson_html)

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
