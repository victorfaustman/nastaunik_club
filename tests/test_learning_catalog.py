import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from bot.database import Database
from bot.learning import get_catalog


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

                material = (await get_catalog(database))["materials"][0]
                self.assertEqual(material["preview_url"], "/mini-app/media/article.jpg")
                self.assertEqual(material["preview_kind"], "image")
                self.assertEqual(material["tags"][0]["name"], "Практика")
                self.assertNotIn("color", material["tags"][0])

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
                    await conn.commit()

                material = (await get_catalog(database))["materials"][0]
                self.assertEqual(material["preview_url"], "/mini-app/media/lesson.mp4")
                self.assertEqual(material["preview_kind"], "video")

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
