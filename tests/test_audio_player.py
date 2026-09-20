"""Audio player selection for MP3 actions (actions/executor.py)."""

import unittest
from unittest import mock

from actions.executor import ActionExecutor

INSTALLED_ALL = {"aplay", "paplay", "mpg123", "ffplay", "afplay"}


def fake_which(installed):
    return lambda name: f"/usr/bin/{name}" if name in installed else None


def fake_process(returncode=0, stderr=b""):
    process = mock.Mock(returncode=returncode)
    process.communicate = mock.AsyncMock(return_value=(b"", stderr))
    return process


class AudioPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def _play(self, target, installed, process=None):
        with mock.patch("actions.executor.shutil.which", fake_which(installed)), mock.patch(
            "actions.executor.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=process or fake_process()),
        ) as spawn:
            await ActionExecutor()._play_audio(target)
        return spawn

    async def test_mp3_prefers_mpg123_over_aplay(self):
        spawn = await self._play("/s/a.mp3", INSTALLED_ALL)
        self.assertEqual(spawn.call_args.args, ("mpg123", "-q", "/s/a.mp3"))

    async def test_mp3_falls_back_to_ffplay(self):
        spawn = await self._play("/s/a.mp3", {"aplay", "paplay", "ffplay"})
        self.assertEqual(
            spawn.call_args.args,
            ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "/s/a.mp3"),
        )

    async def test_mp3_falls_back_to_afplay(self):
        spawn = await self._play("/s/a.mp3", {"afplay"})
        self.assertEqual(spawn.call_args.args, ("afplay", "/s/a.mp3"))

    async def test_mp3_never_uses_aplay_or_paplay(self):
        with self.assertLogs("actions.executor", "WARNING"):
            spawn = await self._play("/s/a.mp3", {"aplay", "paplay"})
        spawn.assert_not_called()

    async def test_wav_uses_aplay(self):
        spawn = await self._play("/s/a.WAV", INSTALLED_ALL)
        self.assertEqual(spawn.call_args.args, ("aplay", "/s/a.WAV"))

    async def test_no_player_logs_warning(self):
        with self.assertLogs("actions.executor", "WARNING") as logs:
            spawn = await self._play("/s/a.mp3", set())
        spawn.assert_not_called()
        self.assertIn("mpg123", logs.output[0])

    async def test_nonzero_exit_logs_stderr(self):
        with self.assertLogs("actions.executor", "ERROR") as logs:
            await self._play("/s/a.mp3", {"mpg123"}, fake_process(1, b"no such file"))
        self.assertIn("code 1", logs.output[0])
        self.assertIn("no such file", logs.output[0])


if __name__ == "__main__":
    unittest.main()
