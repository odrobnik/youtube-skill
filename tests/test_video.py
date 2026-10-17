"""Offline tests for the video command. Google is faked; run: python3 -m unittest discover tests"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # keep scripts/ free of __pycache__
_CONFIG = tempfile.TemporaryDirectory(prefix="youtube-skill-test-")
os.environ["YOUTUBE_SKILL_CONFIG_DIR"] = _CONFIG.name  # never touch the real config or sign-in
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import youtube  # noqa: E402

KEY_CONFIG = {"api_key": "KEY", "client_id": "", "client_secret": ""}
NO_CONFIG = {"api_key": "", "client_id": "", "client_secret": ""}


def video(video_id, title="A video", description="", duration="PT3M30S", live="none", **stats):
    return {"id": video_id,
            "snippet": {"title": title, "description": description, "channelTitle": "Channel",
                        "channelId": "UC1", "publishedAt": "2024-01-15T10:30:00Z",
                        "liveBroadcastContent": live},
            "contentDetails": {"duration": duration},
            "statistics": stats}


class FakeVideosList:
    """Stands in for videos.list: answers with the known videos among the requested IDs."""

    def __init__(self, *videos):
        self.videos = {v["id"]: v for v in videos}
        self.calls = []

    def ids(self, url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.calls.append(query)
        return {"items": [self.videos[i] for i in query["id"][0].split(",") if i in self.videos]}

    def open_json(self, req):  # the API key path
        return self.ids(req.full_url)

    def api_request(self, method, url, tokens, body=None, retry=True):  # the sign-in path
        assert method == "GET" and tokens == {"access_token": "T"}
        return self.ids(url)


def run(*argv):
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["youtube.py", *argv]), \
            mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
        try:
            youtube.main()
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class VideoCommandTest(unittest.TestCase):
    def setUp(self):
        youtube.JSON_MODE = False
        youtube._RESULT = None

    def fake(self, *videos, config=KEY_CONFIG):
        api = FakeVideosList(*videos)
        for target, new in (("_load_config", lambda: dict(config)), ("_open_json", api.open_json),
                            ("api_request", api.api_request)):
            patcher = mock.patch.object(youtube, target, new)
            patcher.start()
            self.addCleanup(patcher.stop)
        return api

    def test_full_details_with_api_key(self):
        description = "Links & notes: https://example.com/?a=1&amp;b=2 <b>as typed</b>\n\n" \
                      "0:00 Intro\n1:23 - Setup\n(12:34) Demo\n1:02:03 Outro"
        api = self.fake(video("dQw4w9WgXcQ", title="Tom &amp; Jerry's \"Best\"", description=description,
                              duration="PT1H5M", viewCount="1234567", likeCount="890"))
        code, out, _ = run("--json", "video", "https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(code, 0)
        (v,) = json.loads(out)
        self.assertEqual(v["title"], "Tom &amp; Jerry's \"Best\"")  # plain text: nothing to decode
        self.assertEqual(v["description"], description)
        self.assertEqual((v["duration"], v["duration_seconds"]), ("1:05:00", 3900))
        self.assertEqual((v["view_count"], v["like_count"], v["comment_count"]), (1234567, 890, None))
        self.assertEqual(v["url"], "https://youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual([(c["timestamp"], c["start_seconds"], c["title"]) for c in v["chapters"]],
                         [("0:00", 0, "Intro"), ("1:23", 83, "Setup"), ("12:34", 754, "Demo"),
                          ("1:02:03", 3723, "Outro")])
        (call,) = api.calls
        self.assertEqual(call["key"], ["KEY"])
        self.assertEqual(call["part"], ["snippet,contentDetails,statistics"])

    def test_sign_in_when_no_api_key(self):
        api = self.fake(video("dQw4w9WgXcQ"), config=NO_CONFIG)
        token_file = Path(_CONFIG.name) / "tokens.json"
        token_file.write_text("{}")
        self.addCleanup(token_file.unlink)
        with mock.patch.object(youtube, "load_tokens", return_value={"access_token": "T"}):
            code, out, _ = run("video", "dQw4w9WgXcQ", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["video_id"], "dQw4w9WgXcQ")
        self.assertNotIn("key", api.calls[0])

    def test_missing_credentials(self):
        api = self.fake(config=NO_CONFIG)
        code, out, _ = run("--json", "video", "dQw4w9WgXcQ")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "missing_credentials")
        self.assertEqual(api.calls, [])

    def test_invalid_input_fails_before_any_request(self):
        api = self.fake(video("dQw4w9WgXcQ"))
        code, out, err = run("--json", "video", "dQw4w9WgXcQ", "https://example.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "invalid_video")
        self.assertIn("Not a YouTube video URL or ID", err)
        self.assertEqual(api.calls, [])

    def test_batches_of_50_in_input_order(self):
        ids = [f"vid{n:08d}" for n in range(120)]
        api = self.fake(*(video(i) for i in ids))
        code, out, _ = run("--json", "video", *reversed(ids))
        self.assertEqual(code, 0)
        self.assertEqual([len(c["id"][0].split(",")) for c in api.calls], [50, 50, 20])
        self.assertEqual([v["video_id"] for v in json.loads(out)], ids[::-1])

    def test_missing_video_keeps_order_and_exits_1(self):
        self.fake(video("aaaaaaaaaaa", title="First"), video("ccccccccccc", title="Third"))
        code, out, err = run("--json", "video", "aaaaaaaaaaa", "bbbbbbbbbbb",
                             "https://www.youtube.com/watch?v=aaaaaaaaaaa", "ccccccccccc")
        self.assertEqual(code, 1)
        result = json.loads(out)  # the whole result is written before the non-zero exit
        self.assertEqual([v["video_id"] for v in result], ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
        self.assertNotIn("found", result[0])
        self.assertEqual(result[1]["found"], False)
        self.assertEqual(result[1]["error"]["code"], "videoNotFound")
        self.assertIn("bbbbbbbbbbb", err)

    def test_live_and_upcoming_have_no_duration(self):
        self.fake(video("aaaaaaaaaaa", duration="P0D", live="live"),
                  video("bbbbbbbbbbb", duration="P0D", live="upcoming"))
        _, out, _ = run("--json", "video", "aaaaaaaaaaa", "bbbbbbbbbbb")
        self.assertEqual([(v["duration"], v["duration_seconds"]) for v in json.loads(out)],
                         [("live", None), ("upcoming", None)])

    def test_text_output(self):
        self.fake(video("dQw4w9WgXcQ", title="Title", description="The whole description.",
                        viewCount="1234567"))
        code, out, _ = run("video", "dQw4w9WgXcQ")
        self.assertEqual(code, 0)
        for text in ("📺 Title", "Published: 2024-01-15", "Duration: 3:30", "Views: 1,234,567",
                     "URL: https://youtube.com/watch?v=dQw4w9WgXcQ", "The whole description."):
            self.assertIn(text, out)

    def test_json_mode_does_not_repeat_the_description_on_stderr(self):
        self.fake(video("dQw4w9WgXcQ", title="Title", description="The whole description."))
        _, out, err = run("--json", "video", "dQw4w9WgXcQ")
        self.assertIn("The whole description.", json.loads(out)[0]["description"])
        self.assertIn("📺 Title", err)
        self.assertNotIn("The whole description.", err)


class HelpersTest(unittest.TestCase):
    def test_duration_seconds(self):
        for iso, seconds in (("PT1H2M3S", 3723), ("PT15M30S", 930), ("PT45S", 45), ("PT2H", 7200),
                             ("PT0S", 0), ("P0D", 0), ("P1DT2H3M4S", 93784),
                             ("P1407DT10H11M52S", 121601512), ("", None), ("P", None),
                             ("PT", None), ("1:00", None)):
            self.assertEqual(youtube._duration_seconds(iso), seconds, iso)

    def test_format_duration(self):
        for seconds, text in ((0, "0:00"), (45, "0:45"), (90, "1:30"), (3723, "1:02:03"),
                              (93784, "26:03:04")):
            self.assertEqual(youtube._format_duration(seconds), text)

    def test_chapters_follow_youtube_rules(self):
        def titles(description):
            return [c["title"] for c in youtube._chapters(description)]

        self.assertEqual(titles("0:00 A\n0:30 B\n1:00 C"), ["A", "B", "C"])
        self.assertEqual(titles("00:00 A\n00:30 B\n01:00 C"), ["A", "B", "C"])
        self.assertEqual(titles("[0:00] A\n0:30 – B\n1:00 | C"), ["A", "B", "C"])
        self.assertEqual(titles("0:00 A\n0:30 B"), [])  # fewer than three
        self.assertEqual(titles("0:15 A\n0:30 B\n1:00 C"), [])  # doesn't start at 0:00
        self.assertEqual(titles("Doors 19:30 tonight\n12:00 noon\n0:00 A\n0:30 B\n1:00 C"), ["A", "B", "C"])
        self.assertEqual(titles("0:00 A\n0:30 B\n1:00 C\n\nSongs:\n0:10 D\n2:00 E"), ["A", "B", "C"])
        self.assertEqual(titles("Just text, no timestamps."), [])
        self.assertEqual(titles("0:00 A\n0:10 B\n0:20 C"), ["A", "B", "C"])  # 10 seconds is enough
        self.assertEqual(titles("0:00 A\n0:05 B\n0:20 C"), [])  # a chapter under 10 seconds

    def test_last_chapter_needs_10_seconds_of_video(self):
        description = "0:00 A\n0:30 B\n1:00 C"
        self.assertEqual(len(youtube._chapters(description, 70)), 3)
        self.assertEqual(youtube._chapters(description, 65), [])  # the last one would be 5 seconds
        self.assertEqual(youtube._chapters(description, 50), [])  # starts after the video ends
        self.assertEqual(len(youtube._chapters(description, None)), 3)  # length unknown (live)


if __name__ == "__main__":
    unittest.main()
