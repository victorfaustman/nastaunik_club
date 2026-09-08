import asyncio
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from bot.database import Database
from bot.learning_admin_v2 import LearningAdmin


class VideoProcessingQueueTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
    def test_static_video_poster_is_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "sample.mp4"
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_path),
                ],
                check=True,
            )
            admin = LearningAdmin(root / "mini.db", lambda path, **query: path)
            poster_name = asyncio.run(admin.create_video_poster(video_path))
            self.assertEqual(poster_name, "sample.poster.webp")
            self.assertGreater((root / poster_name).stat().st_size, 0)

    def test_inline_video_waits_for_save_then_enters_queue(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database_path = root / "mini.db"
                video_path = root / "content-test.mp4"
                video_path.write_bytes(b"not-a-real-video")

                schema = Database(database_path)
                await schema.init()
                admin = LearningAdmin(database_path, lambda path, **query: path)
                db = await admin.connect()
                try:
                    now = datetime.utcnow().isoformat(timespec="seconds")
                    await admin.enqueue_video(db, video_path, "waiting_save")
                    await db.execute(
                        """INSERT INTO mini_app_materials(
                               title,full_description,status,sort_order,created_at,updated_at
                           ) VALUES(?,?,'published',0,?,?)""",
                        ("Тест", f'<video src="/mini-app/media/{video_path.name}"></video>', now, now),
                    )
                    await db.commit()

                    jobs = await admin.material_video_jobs(db, 1)
                    self.assertEqual(jobs[0]["status"], "waiting_save")

                    await admin.activate_saved_videos(db, f'<video src="/mini-app/media/{video_path.name}"></video>')
                    await db.commit()
                finally:
                    await db.close()

                job = await admin.claim_video_job()
                self.assertIsNotNone(job)
                self.assertEqual(job["stored_name"], video_path.name)

                db = await admin.connect()
                try:
                    jobs = await admin.material_video_jobs(db, 1)
                    self.assertEqual(jobs[0]["status"], "processing")
                finally:
                    await db.close()

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
