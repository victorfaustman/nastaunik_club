import sqlite3
import unittest
from pathlib import Path


class MutualRelationsTests(unittest.TestCase):
    def test_backfill_add_delete_and_repeated_initialization(self):
        source = (Path(__file__).resolve().parents[1] / 'bot/database.py').read_text(encoding='utf-8')
        schema = source.split('CREATE TABLE IF NOT EXISTS mini_app_material_relations (', 1)[1]
        schema = 'CREATE TABLE IF NOT EXISTS mini_app_material_relations (' + schema.split('CREATE TABLE IF NOT EXISTS mini_app_video_jobs', 1)[0]
        with sqlite3.connect(':memory:') as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA recursive_triggers=ON')
            db.execute('CREATE TABLE mini_app_materials (id INTEGER PRIMARY KEY)')
            db.executemany('INSERT INTO mini_app_materials VALUES(?)', [(1,), (2,), (3,)])
            db.executescript(schema.split('CREATE TRIGGER', 1)[0])
            db.execute("INSERT INTO mini_app_material_relations VALUES(1,2,0,'test')")
            db.executescript(schema)
            pairs = lambda: set(db.execute('SELECT material_id,related_material_id FROM mini_app_material_relations'))
            self.assertEqual(pairs(), {(1, 2), (2, 1)})
            db.executescript(schema)
            self.assertEqual(pairs(), {(1, 2), (2, 1)})
            db.execute("INSERT INTO mini_app_material_relations VALUES(1,3,1,'test')")
            self.assertEqual(pairs(), {(1, 2), (2, 1), (1, 3), (3, 1)})
            db.execute('DELETE FROM mini_app_material_relations WHERE material_id=2 AND related_material_id=1')
            self.assertEqual(pairs(), {(1, 3), (3, 1)})
            db.executescript(schema)
            self.assertEqual(pairs(), {(1, 3), (3, 1)})
            db.execute('DELETE FROM mini_app_materials WHERE id=3')
            self.assertEqual(pairs(), set())
