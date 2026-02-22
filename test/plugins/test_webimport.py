"""Tests for the 'webimport' plugin."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from beets.test.helper import TestHelper
from beetsplug import webimport
from beetsplug.webimport.session import (
    WebImportSession,
    _serialize_candidate,
    _serialize_task_info,
)


class WebImportPluginTest(unittest.TestCase, TestHelper):
    def setUp(self):
        self.setup_beets()
        webimport.app.config["TESTING"] = True
        webimport.app.config["lib"] = self.lib
        self.client = webimport.app.test_client()

    def tearDown(self):
        self.teardown_beets()

    def test_home_page(self):
        response = self.client.get("/")
        assert response.status_code == 200
        assert b"Beets Web Import" in response.data

    def test_start_import_missing_paths(self):
        response = self.client.post(
            "/api/start",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_start_import_empty_paths(self):
        response = self.client.post(
            "/api/start",
            data=json.dumps({"paths": []}),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_start_import_nonexistent_path(self):
        response = self.client.post(
            "/api/start",
            data=json.dumps({"paths": ["/nonexistent/path/xyz"]}),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert "does not exist" in data["error"]

    def test_start_import_valid_path(self):
        tmpdir = tempfile.mkdtemp()
        try:
            response = self.client.post(
                "/api/start",
                data=json.dumps({"paths": [tmpdir]}),
                content_type="application/json",
            )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "session_id" in data
            assert data["status"] == "started"
        finally:
            shutil.rmtree(tmpdir)

    def test_get_question_invalid_session(self):
        response = self.client.get("/api/session/invalid/question")
        assert response.status_code == 404

    def test_post_answer_invalid_session(self):
        response = self.client.post(
            "/api/session/invalid/answer",
            data=json.dumps({"action": "skip"}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_get_status_invalid_session(self):
        response = self.client.get("/api/session/invalid/status")
        assert response.status_code == 404

    def test_delete_session_invalid(self):
        response = self.client.delete("/api/session/invalid")
        assert response.status_code == 404

    def test_delete_session_valid(self):
        tmpdir = tempfile.mkdtemp()
        try:
            # Start a session first.
            response = self.client.post(
                "/api/start",
                data=json.dumps({"paths": [tmpdir]}),
                content_type="application/json",
            )
            data = json.loads(response.data)
            session_id = data["session_id"]

            # Delete it.
            response = self.client.delete(f"/api/session/{session_id}")
            assert response.status_code == 200
            result = json.loads(response.data)
            assert result["status"] == "deleted"
        finally:
            shutil.rmtree(tmpdir)


class WebImportSessionTest(unittest.TestCase, TestHelper):
    def setUp(self):
        self.setup_beets()

    def tearDown(self):
        self.teardown_beets()

    def test_session_creation(self):
        session = WebImportSession(self.lib, None, [], None)
        assert session.status == "idle"
        assert session._error is None

    def test_choose_match_skip(self):
        """Test that choose_match returns SKIP when answer is skip."""
        session = WebImportSession(self.lib, None, [], None)

        task = MagicMock()
        task.candidates = []
        task.rec = None
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = []
        task.cur_artist = "Test Artist"
        task.cur_album = "Test Album"

        # Pre-fill the answer queue.
        session.answer_queue.put({"action": "skip"})
        result = session.choose_match(task)

        from beets.importer.tasks import Action

        assert result == Action.SKIP

    def test_choose_match_asis(self):
        """Test that choose_match returns ASIS when answer is asis."""
        session = WebImportSession(self.lib, None, [], None)

        task = MagicMock()
        task.candidates = []
        task.rec = None
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = []
        task.cur_artist = "Test Artist"
        task.cur_album = "Test Album"

        session.answer_queue.put({"action": "asis"})
        result = session.choose_match(task)

        from beets.importer.tasks import Action

        assert result == Action.ASIS

    def test_choose_match_apply(self):
        """Test that choose_match returns a candidate when applying."""
        session = WebImportSession(self.lib, None, [], None)

        candidate = MagicMock()
        candidate.distance = 0.1
        candidate.info.artist = "Matched Artist"
        candidate.info.name = "Matched Album"

        task = MagicMock()
        task.candidates = [candidate]
        task.rec = MagicMock()
        task.rec.name = "strong"
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = []
        task.cur_artist = "Test Artist"
        task.cur_album = "Test Album"

        session.answer_queue.put({"action": "apply", "candidate_index": 0})
        result = session.choose_match(task)

        assert result == candidate

    def test_choose_item_skip(self):
        """Test that choose_item returns SKIP."""
        session = WebImportSession(self.lib, None, [], None)

        task = MagicMock()
        task.candidates = []
        task.rec = None
        task.is_album = False
        task.paths = [b"/test/path"]
        task.items = []
        task.item.artist = "Test Artist"
        task.item.title = "Test Title"
        task.item.path = b"/test/path/song.mp3"

        session.answer_queue.put({"action": "skip"})
        result = session.choose_item(task)

        from beets.importer.tasks import Action

        assert result == Action.SKIP

    def test_resolve_duplicate_skip(self):
        """Test that resolve_duplicate sets SKIP choice."""
        session = WebImportSession(self.lib, None, [], None)

        task = MagicMock()
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = []
        task.cur_artist = "Test"
        task.cur_album = "Test"

        dup = MagicMock()
        dup.id = 1
        dup.album = "Dup Album"
        dup.albumartist = "Dup Artist"
        dup.items.return_value = []

        session.answer_queue.put({"action": "skip"})
        session.resolve_duplicate(task, [dup])

        from beets.importer.tasks import Action

        task.set_choice.assert_called_with(Action.SKIP)

    def test_resolve_duplicate_keep(self):
        """Test that resolve_duplicate keeps both."""
        session = WebImportSession(self.lib, None, [], None)

        task = MagicMock()
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = []
        task.cur_artist = "Test"
        task.cur_album = "Test"

        dup = MagicMock()
        dup.id = 1
        dup.album = "Dup Album"
        dup.albumartist = "Dup Artist"
        dup.items.return_value = []

        session.answer_queue.put({"action": "keep"})
        session.resolve_duplicate(task, [dup])

        # Keep both means set_choice is NOT called.
        task.set_choice.assert_not_called()

    def test_resolve_duplicate_remove(self):
        """Test that resolve_duplicate removes old."""
        session = WebImportSession(self.lib, None, [], None)

        task = MagicMock()
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = []
        task.cur_artist = "Test"
        task.cur_album = "Test"

        dup = MagicMock()
        dup.id = 1
        dup.album = "Dup Album"
        dup.albumartist = "Dup Artist"
        dup.items.return_value = []

        session.answer_queue.put({"action": "remove"})
        session.resolve_duplicate(task, [dup])

        assert task.should_remove_duplicates is True

    def test_should_resume_yes(self):
        """Test that should_resume returns True."""
        session = WebImportSession(self.lib, None, [], None)
        session.answer_queue.put({"resume": True})
        result = session.should_resume(b"/test/path")
        assert result is True

    def test_should_resume_no(self):
        """Test that should_resume returns False."""
        session = WebImportSession(self.lib, None, [], None)
        session.answer_queue.put({"resume": False})
        result = session.should_resume(b"/test/path")
        assert result is False


class SerializationTest(unittest.TestCase):
    def test_serialize_candidate_album(self):
        """Test serialization of an album match candidate."""
        from beets.autotag import AlbumMatch

        distance_mock = MagicMock()
        distance_mock.__float__ = MagicMock(return_value=0.15)
        distance_mock.items.return_value = [("artist", 0.1)]

        match = MagicMock()
        match.__class__ = AlbumMatch
        match.distance = distance_mock
        match.info.artist = "Test Artist"
        match.info.name = "Test Album"
        match.info.album = "Test Album"
        match.info.tracks = []
        match.info.year = 2024
        match.info.label = "Test Label"
        match.info.data_source = "MusicBrainz"
        match.info.album_id = "abc123"
        match.extra_items = []
        match.extra_tracks = []

        result = _serialize_candidate(match, 0)

        assert result["index"] == 0
        assert result["distance"] == 0.15
        assert result["similarity"] == 85.0
        assert result["artist"] == "Test Artist"
        assert result["type"] == "album"

    def test_serialize_task_info_album(self):
        """Test serialization of album task info."""
        task = MagicMock()
        task.is_album = True
        task.paths = [b"/test/path"]
        task.items = [MagicMock(), MagicMock()]
        task.cur_artist = "Test Artist"
        task.cur_album = "Test Album"

        result = _serialize_task_info(task)

        assert result["is_album"] is True
        assert result["num_items"] == 2
        assert result["cur_artist"] == "Test Artist"


class WebImportPluginClassTest(unittest.TestCase):
    def test_plugin_instantiation(self):
        plugin = webimport.WebImportPlugin()
        assert plugin.config["host"].get() == "127.0.0.1"
        assert plugin.config["port"].get() == 8338

    def test_plugin_commands(self):
        plugin = webimport.WebImportPlugin()
        commands = plugin.commands()
        assert len(commands) == 1
        assert commands[0].name == "webimport"


if __name__ == "__main__":
    unittest.main()
