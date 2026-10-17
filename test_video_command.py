#!/usr/bin/env python3
"""Test script for the video command with mocked API responses."""

import json
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

# Mock the config file to not exist before importing
with patch('pathlib.Path.exists', return_value=False):
    import youtube


class TestVideoCommand(unittest.TestCase):
    """Test the video command functionality."""

    def setUp(self):
        """Set up test fixtures."""
        youtube.JSON_MODE = False
        youtube._RESULT = None

    def test_extract_video_id_from_various_urls(self):
        """Test video ID extraction from different URL formats."""
        test_cases = [
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("not-a-valid-id", None),
            ("https://example.com/watch?v=invalid", None),
        ]
        
        for url, expected in test_cases:
            result = youtube.extract_video_id(url)
            self.assertEqual(result, expected, f"Failed for: {url}")

    def test_parse_duration(self):
        """Test ISO 8601 duration parsing."""
        test_cases = [
            ("PT1H2M3S", 3723),  # 1h 2m 3s
            ("PT15M30S", 930),   # 15m 30s
            ("PT45S", 45),       # 45s
            ("PT2H", 7200),      # 2h
            ("PT1M", 60),        # 1m
            ("", 0),             # empty
            ("PT0S", 0),         # zero
        ]
        
        for duration_iso, expected in test_cases:
            result = youtube._parse_duration(duration_iso)
            self.assertEqual(result, expected, f"Failed for: {duration_iso}")

    def test_format_duration(self):
        """Test duration formatting."""
        test_cases = [
            (0, "0:00"),
            (45, "0:45"),
            (60, "1:00"),
            (90, "1:30"),
            (3723, "1:02:03"),  # 1h 2m 3s
            (7265, "2:01:05"),  # 2h 1m 5s
        ]
        
        for seconds, expected in test_cases:
            result = youtube._format_duration(seconds)
            self.assertEqual(result, expected, f"Failed for: {seconds}s")

    def test_extract_chapters(self):
        """Test chapter extraction from descriptions."""
        # Description with chapters
        desc_with_chapters = """Great video about Python!

0:00 Introduction
1:23 Getting Started
5:45 Advanced Topics
12:30 Conclusion

Check out my website: https://example.com"""
        
        chapters = youtube._extract_chapters(desc_with_chapters)
        self.assertEqual(len(chapters), 4)
        self.assertEqual(chapters[0]["timestamp"], "0:00")
        self.assertEqual(chapters[0]["title"], "Introduction")
        self.assertEqual(chapters[1]["timestamp"], "1:23")
        self.assertEqual(chapters[1]["title"], "Getting Started")

        # Description without chapters
        desc_without_chapters = "Just a regular description without timestamps."
        chapters = youtube._extract_chapters(desc_without_chapters)
        self.assertEqual(len(chapters), 0)

        # Description with only one timestamp (should not return chapters)
        desc_one_timestamp = "0:00 Only one timestamp here"
        chapters = youtube._extract_chapters(desc_one_timestamp)
        self.assertEqual(len(chapters), 0)

        # Description with hour:minute:second format
        desc_long_format = """0:00:00 Start
1:23:45 Middle
2:30:00 End"""
        chapters = youtube._extract_chapters(desc_long_format)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[1]["timestamp"], "1:23:45")

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_command_with_api_key(self, mock_open_json, mock_load_config):
        """Test video command with API key (no OAuth)."""
        # Mock configuration with API key
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        # Mock API response
        mock_open_json.return_value = {
            "items": [
                {
                    "id": "dQw4w9WgXcQ",
                    "snippet": {
                        "title": "Test Video Title",
                        "description": "0:00 Intro\n1:23 Main Content\n\nFull description here with links: https://example.com",
                        "channelTitle": "Test Channel",
                        "channelId": "UCtest123",
                        "publishedAt": "2024-01-15T10:30:00Z"
                    },
                    "contentDetails": {
                        "duration": "PT5M30S"
                    },
                    "statistics": {
                        "viewCount": "1000000",
                        "likeCount": "50000",
                        "commentCount": "2000"
                    }
                }
            ]
        }

        # Create mock args
        args = Mock()
        args.videos = ["dQw4w9WgXcQ"]

        # Run command
        with patch('builtins.print'):  # Suppress output
            youtube.cmd_video(args)

        # Verify result
        self.assertIsNotNone(youtube._RESULT)
        self.assertEqual(len(youtube._RESULT), 1)
        result = youtube._RESULT[0]
        self.assertEqual(result["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(result["title"], "Test Video Title")
        self.assertEqual(result["duration"], "5:30")
        self.assertEqual(result["duration_seconds"], 330)
        self.assertIn("Full description here", result["description"])
        self.assertEqual(len(result["chapters"]), 2)
        self.assertEqual(result["view_count"], "1000000")

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_command_not_found(self, mock_open_json, mock_load_config):
        """Test video command with non-existent video ID."""
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        # Mock API response with no items (video not found)
        mock_open_json.return_value = {"items": []}

        args = Mock()
        args.videos = ["notfound123"]

        with patch('builtins.print'):
            with self.assertRaises(SystemExit) as cm:
                youtube.cmd_video(args)
            self.assertEqual(cm.exception.code, 1)

        # Verify result was recorded before exit
        self.assertIsNotNone(youtube._RESULT)
        self.assertEqual(len(youtube._RESULT), 1)
        result = youtube._RESULT[0]
        self.assertEqual(result["video_id"], "notfound123")
        self.assertEqual(result["found"], False)
        self.assertIn("error", result)

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_command_multiple_videos(self, mock_open_json, mock_load_config):
        """Test video command with multiple video IDs."""
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        # Mock API response with multiple videos (use valid 11-char IDs)
        mock_open_json.return_value = {
            "items": [
                {
                    "id": "abc12345678",
                    "snippet": {
                        "title": "Video 1",
                        "description": "Description 1",
                        "channelTitle": "Channel 1",
                        "channelId": "UC1",
                        "publishedAt": "2024-01-01T10:00:00Z"
                    },
                    "contentDetails": {"duration": "PT1M30S"},
                    "statistics": {}
                },
                {
                    "id": "xyz98765432",
                    "snippet": {
                        "title": "Video 2",
                        "description": "Description 2",
                        "channelTitle": "Channel 2",
                        "channelId": "UC2",
                        "publishedAt": "2024-01-02T10:00:00Z"
                    },
                    "contentDetails": {"duration": "PT10M"},
                    "statistics": {}
                }
            ]
        }

        args = Mock()
        args.videos = ["abc12345678", "xyz98765432"]

        with patch('builtins.print'):
            youtube.cmd_video(args)

        # Verify result
        self.assertIsNotNone(youtube._RESULT)
        self.assertEqual(len(youtube._RESULT), 2)
        self.assertEqual(youtube._RESULT[0]["video_id"], "abc12345678")
        self.assertEqual(youtube._RESULT[1]["video_id"], "xyz98765432")

    def test_invalid_video_url(self):
        """Test video command with invalid URL."""
        args = Mock()
        args.videos = ["not-a-valid-url"]

        with patch('builtins.print'):
            with self.assertRaises(SystemExit) as cm:
                youtube.cmd_video(args)
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    print("Running tests for video command...\n")
    unittest.main(verbosity=2)
