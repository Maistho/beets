# This file is part of beets.
# Copyright 2016, Adrian Sampson.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

"""Import session for the webimport plugin.

Provides a WebImportSession that communicates with the web frontend
using thread-safe queues for interactive import decisions.
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING

from beets import autotag, logging
from beets.importer.session import ImportSession
from beets.importer.tasks import Action
from beets.util import displayable_path

if TYPE_CHECKING:
    from beets.importer.tasks import ImportTask

log = logging.getLogger("beets")


def _serialize_candidate(match, index):
    """Serialize an AlbumMatch or TrackMatch to a JSON-compatible dict."""
    info = match.info
    dist = float(match.distance)
    penalties = dict(match.distance.items()) if hasattr(match.distance, "items") else {}

    result = {
        "index": index,
        "distance": dist,
        "similarity": round((1 - dist) * 100, 1),
        "artist": getattr(info, "artist", ""),
        "name": getattr(info, "name", "") or getattr(info, "title", ""),
        "penalties": {k: float(v) for k, v in penalties.items()},
    }

    # Add album-specific fields.
    if isinstance(match, autotag.AlbumMatch):
        result["type"] = "album"
        result["album"] = getattr(info, "album", "")
        result["num_tracks"] = len(getattr(info, "tracks", []))
        result["year"] = getattr(info, "year", None)
        result["label"] = getattr(info, "label", None)
        result["data_source"] = getattr(info, "data_source", None)
        result["album_id"] = getattr(info, "album_id", None)
        result["extra_items"] = len(match.extra_items)
        result["extra_tracks"] = len(match.extra_tracks)
    else:
        result["type"] = "track"
        result["title"] = getattr(info, "title", "")
        result["track_id"] = getattr(info, "track_id", None)
        result["data_source"] = getattr(info, "data_source", None)

    return result


def _serialize_task_info(task):
    """Serialize basic task info for the frontend."""
    result = {
        "is_album": task.is_album,
        "paths": [displayable_path(p) for p in task.paths],
        "num_items": len(task.items),
    }
    if task.is_album:
        result["cur_artist"] = task.cur_artist or ""
        result["cur_album"] = task.cur_album or ""
    else:
        item = task.item
        result["cur_artist"] = getattr(item, "artist", "")
        result["cur_title"] = getattr(item, "title", "")
        result["item_path"] = displayable_path(item.path)
    return result


class WebImportSession(ImportSession):
    """An import session that communicates with a web frontend.

    Uses two queues:
    - question_queue: session puts questions for the UI
    - answer_queue: UI puts answers back to the session
    """

    def __init__(self, lib, loghandler, paths, query):
        super().__init__(lib, loghandler, paths, query)
        self.question_queue = queue.Queue()
        self.answer_queue = queue.Queue()
        self._import_thread = None
        self._status = "idle"
        self._error = None

    @property
    def status(self):
        return self._status

    def start(self):
        """Start the import in a background thread."""
        self._status = "running"
        self._error = None
        self._import_thread = threading.Thread(
            target=self._run_import, daemon=True
        )
        self._import_thread.start()

    def _run_import(self):
        """Run the import pipeline in a background thread."""
        try:
            self.run()
            self._status = "completed"
        except Exception as e:
            self._error = str(e)
            self._status = "error"
        finally:
            # Signal that no more questions will come.
            self.question_queue.put({"type": "done", "status": self._status})

    def _ask(self, question):
        """Put a question on the queue and wait for an answer."""
        self.question_queue.put(question)
        return self.answer_queue.get()

    def choose_match(self, task):
        """Ask the web UI which album match to apply."""
        candidates = [
            _serialize_candidate(c, i)
            for i, c in enumerate(task.candidates)
        ]

        question = {
            "type": "choose_match",
            "task": _serialize_task_info(task),
            "candidates": candidates,
            "recommendation": task.rec.name if task.rec else "none",
        }

        answer = self._ask(question)
        action = answer.get("action", "skip")

        if action == "skip":
            return Action.SKIP
        elif action == "asis":
            return Action.ASIS
        elif action == "tracks":
            return Action.TRACKS
        elif action == "apply":
            idx = answer.get("candidate_index", 0)
            if 0 <= idx < len(task.candidates):
                return task.candidates[idx]
            return Action.SKIP
        elif action == "search":
            artist = answer.get("artist", "")
            album_name = answer.get("name", "")
            _, _, prop = autotag.tag_album(task.items, artist, album_name)
            task.candidates = prop.candidates
            task.rec = prop.recommendation
            return self.choose_match(task)
        elif action == "search_id":
            search_id = answer.get("id", "")
            _, _, prop = autotag.tag_album(
                task.items, search_ids=search_id.split()
            )
            task.candidates = prop.candidates
            task.rec = prop.recommendation
            return self.choose_match(task)
        else:
            return Action.SKIP

    def choose_item(self, task):
        """Ask the web UI which track match to apply."""
        candidates = [
            _serialize_candidate(c, i)
            for i, c in enumerate(task.candidates)
        ]

        question = {
            "type": "choose_item",
            "task": _serialize_task_info(task),
            "candidates": candidates,
            "recommendation": task.rec.name if task.rec else "none",
        }

        answer = self._ask(question)
        action = answer.get("action", "skip")

        if action == "skip":
            return Action.SKIP
        elif action == "asis":
            return Action.ASIS
        elif action == "apply":
            idx = answer.get("candidate_index", 0)
            if 0 <= idx < len(task.candidates):
                return task.candidates[idx]
            return Action.SKIP
        elif action == "search":
            artist = answer.get("artist", "")
            title = answer.get("name", "")
            prop = autotag.tag_item(task.item, artist, title)
            task.candidates = prop.candidates
            task.rec = prop.recommendation
            return self.choose_item(task)
        elif action == "search_id":
            search_id = answer.get("id", "")
            prop = autotag.tag_item(
                task.item, search_ids=search_id.split()
            )
            task.candidates = prop.candidates
            task.rec = prop.recommendation
            return self.choose_item(task)
        else:
            return Action.SKIP

    def resolve_duplicate(self, task, found_duplicates):
        """Ask the web UI how to handle a duplicate."""
        dup_info = []
        for dup in found_duplicates:
            if task.is_album:
                items = list(dup.items())
                dup_info.append({
                    "type": "album",
                    "id": dup.id,
                    "album": dup.album,
                    "artist": dup.albumartist,
                    "num_items": len(items),
                })
            else:
                dup_info.append({
                    "type": "item",
                    "id": dup.id,
                    "title": dup.title,
                    "artist": dup.artist,
                })

        question = {
            "type": "resolve_duplicate",
            "task": _serialize_task_info(task),
            "duplicates": dup_info,
            "is_album": task.is_album,
        }

        answer = self._ask(question)
        action = answer.get("action", "skip")

        if action == "skip":
            task.set_choice(Action.SKIP)
        elif action == "keep":
            pass  # Keep both.
        elif action == "remove":
            task.should_remove_duplicates = True
        elif action == "merge":
            task.should_merge_duplicates = True

    def should_resume(self, path):
        """Ask the web UI whether to resume an interrupted import."""
        question = {
            "type": "should_resume",
            "path": displayable_path(path),
        }
        answer = self._ask(question)
        return answer.get("resume", True)
