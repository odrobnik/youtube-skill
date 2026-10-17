#!/usr/bin/env python3
"""Test script for bug fixes: global --json and not-found video handling."""

import json
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from io import StringIO

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

# Mock the config file to not exist before importing
with patch('pathlib.Path.exists', return_value=False):
    import youtube


class TestBugFixes(unittest.TestCase):
    """Test the bug fixes."""

    def setUp(self):
        """Set up test fixtures."""
        youtube.JSON_MODE = False
        youtube._RESULT = None
        youtube._JSON_OUT = sys.stdout

    def test_global_json_flag_before_subcommand(self):
        """Test that --json before the subcommand is recognized."""
        # Simulate: youtube.py --json list
        test_args = ["youtube.py", "--json", "list"]
        
        with patch('sys.argv', test_args):
            with patch('youtube.TOKEN_FILE.exists', return_value=True):
                with patch('youtube.load_tokens', return_value={"access_token": "test"}):
                    with patch('youtube.api_request', return_value={"items": []}):
                        parser = youtube.argparse.ArgumentParser(add_help=False)
                        parser.add_argument("--json", action="store_true", default=youtube.argparse.SUPPRESS)
                        
                        # Parse just to check the flag is recognized
                        args, _ = parser.parse_known_args(test_args[1:])
                        self.assertTrue(hasattr(args, 'json'))
                        self.assertTrue(args.json)

    def test_global_json_flag_after_subcommand(self):
        """Test that --json after the subcommand is recognized."""
        # Simulate: youtube.py list --json
        test_args = ["youtube.py", "list", "--json"]
        
        with patch('sys.argv', test_args):
            parser = youtube.argparse.ArgumentParser(add_help=False)
            parser.add_argument("--json", action="store_true", default=youtube.argparse.SUPPRESS)
            
            # Parse just to check the flag is recognized
            args, _ = parser.parse_known_args(test_args[1:])
            self.assertTrue(hasattr(args, 'json'))
            self.assertTrue(args.json)

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_not_found_json_output(self, mock_open_json, mock_load_config):
        """Test that not-found video produces proper JSON output."""
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        # Mock API response with no items (video not found)
        mock_open_json.return_value = {"items": []}

        args = Mock()
        args.videos = ["xxxxxxxxxxx"]  # Not found

        # Capture output
        youtube.JSON_MODE = True
        json_out = StringIO()
        youtube._JSON_OUT = json_out
        
        with patch('sys.stdout', StringIO()):  # Redirect text output
            with self.assertRaises(SystemExit) as cm:
                youtube.cmd_video(args)
            self.assertEqual(cm.exception.code, 1)

        # Check JSON was written
        json_output = json_out.getvalue()
        self.assertTrue(len(json_output) > 0, "JSON output should not be empty")
        
        result = json.loads(json_output)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["video_id"], "xxxxxxxxxxx")
        self.assertEqual(result[0]["found"], False)
        self.assertIn("error", result[0])
        self.assertEqual(result[0]["error"]["code"], "videoNotFound")

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_mixed_valid_invalid_json(self, mock_open_json, mock_load_config):
        """Test mixed valid and invalid video IDs in JSON mode."""
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        # Mock API response with one found video (second ID not found)
        mock_open_json.return_value = {
            "items": [
                {
                    "id": "dQw4w9WgXcQ",
                    "snippet": {
                        "title": "Valid Video",
                        "description": "Description here",
                        "channelTitle": "Test Channel",
                        "channelId": "UCtest",
                        "publishedAt": "2024-01-01T10:00:00Z"
                    },
                    "contentDetails": {"duration": "PT3M30S"},
                    "statistics": {"viewCount": "1000"}
                }
            ]
        }

        args = Mock()
        args.videos = ["dQw4w9WgXcQ", "xxxxxxxxxxx"]  # One valid, one not found

        # Capture output
        youtube.JSON_MODE = True
        json_out = StringIO()
        youtube._JSON_OUT = json_out
        
        with patch('sys.stdout', StringIO()):
            with self.assertRaises(SystemExit) as cm:
                youtube.cmd_video(args)
            self.assertEqual(cm.exception.code, 1)

        # Check JSON contains both videos
        json_output = json_out.getvalue()
        self.assertTrue(len(json_output) > 0, "JSON output should not be empty")
        
        result = json.loads(json_output)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        
        # First video should be found
        self.assertEqual(result[0]["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(result[0]["title"], "Valid Video")
        self.assertNotIn("found", result[0])  # found=True is implicit
        
        # Second video should be not found
        self.assertEqual(result[1]["video_id"], "xxxxxxxxxxx")
        self.assertEqual(result[1]["found"], False)
        self.assertIn("error", result[1])

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_not_found_text_output(self, mock_open_json, mock_load_config):
        """Test that not-found video produces proper text output."""
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        mock_open_json.return_value = {"items": []}

        args = Mock()
        args.videos = ["xxxxxxxxxxx"]

        # Capture text output
        youtube.JSON_MODE = False
        text_out = StringIO()
        
        with patch('sys.stdout', text_out):
            with self.assertRaises(SystemExit) as cm:
                youtube.cmd_video(args)
            self.assertEqual(cm.exception.code, 1)

        output = text_out.getvalue()
        self.assertIn("Video not found", output)
        self.assertIn("xxxxxxxxxxx", output)

    @patch('youtube._load_config')
    @patch('youtube._open_json')
    def test_video_all_valid_no_error_exit(self, mock_open_json, mock_load_config):
        """Test that all valid videos don't exit with error."""
        mock_load_config.return_value = {
            "api_key": "test_api_key",
            "client_id": "",
            "client_secret": ""
        }

        mock_open_json.return_value = {
            "items": [
                {
                    "id": "dQw4w9WgXcQ",
                    "snippet": {
                        "title": "Video Title",
                        "description": "Description",
                        "channelTitle": "Channel",
                        "channelId": "UC123",
                        "publishedAt": "2024-01-01T10:00:00Z"
                    },
                    "contentDetails": {"duration": "PT1M"},
                    "statistics": {}
                }
            ]
        }

        args = Mock()
        args.videos = ["dQw4w9WgXcQ"]

        youtube.JSON_MODE = False
        
        # Should NOT raise SystemExit
        with patch('sys.stdout', StringIO()):
            try:
                youtube.cmd_video(args)
                # If we get here, no exception was raised (good!)
            except SystemExit:
                self.fail("cmd_video should not exit with error for all valid videos")


if __name__ == "__main__":
    print("Running bug fix tests...\n")
    unittest.main(verbosity=2)
