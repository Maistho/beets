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

"""A Web interface for importing music into a beets library.

Provides a modern web UI with drag-and-drop support for importing
music folders. Supports interactive tagging with the same decision
flow as the CLI importer.
"""

from __future__ import annotations

import os
import queue
import shutil
import tempfile

import flask
from flask import jsonify

from beets import ui, util
from beets.plugins import BeetsPlugin

from .session import WebImportSession

app = flask.Flask(__name__)

# Active import sessions keyed by session ID.
_sessions: dict[str, WebImportSession] = {}
_next_session_id = 0
_session_lock = __import__("threading").Lock()


def _get_lib():
    return app.config["lib"]


def _new_session_id():
    global _next_session_id
    with _session_lock:
        _next_session_id += 1
        return str(_next_session_id)


# ----------------------------- API Routes ---------------------------------- #


@app.route("/")
def home():
    return flask.render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_import():
    """Start a new import session for the given path(s).

    Expects JSON body: {"paths": ["/path/to/music"]}
    """
    data = flask.request.get_json()
    if not data or "paths" not in data:
        return jsonify({"error": "Missing 'paths' in request body"}), 400

    paths = data["paths"]
    if not paths:
        return jsonify({"error": "No paths provided"}), 400

    # Validate that paths exist.
    for p in paths:
        if not os.path.exists(p):
            return jsonify({"error": f"Path does not exist: {p}"}), 400

    lib = _get_lib()
    session_id = _new_session_id()

    # Convert paths to bytes as beets expects.
    byte_paths = [util.bytestring_path(p) for p in paths]

    session = WebImportSession(lib, None, byte_paths, None)
    _sessions[session_id] = session
    session.start()

    return jsonify({"session_id": session_id, "status": "started"})


@app.route("/api/session/<session_id>/question")
def get_question(session_id):
    """Poll for the next question from the import session.

    Returns the question or a status update. Uses long-polling with
    a timeout to avoid busy-waiting.
    """
    session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    try:
        question = session.question_queue.get(timeout=30)
        return jsonify(question)
    except queue.Empty:
        return jsonify({"type": "waiting", "status": session.status})


@app.route("/api/session/<session_id>/answer", methods=["POST"])
def post_answer(session_id):
    """Submit an answer to the current import question."""
    session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = flask.request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    session.answer_queue.put(data)
    return jsonify({"status": "ok"})


@app.route("/api/session/<session_id>/status")
def get_status(session_id):
    """Get the current status of an import session."""
    session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    result = {"status": session.status}
    if session._error:
        result["error"] = session._error
    return jsonify(result)


@app.route("/api/session/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    """Clean up an import session."""
    session = _sessions.pop(session_id, None)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"status": "deleted"})


@app.route("/api/upload", methods=["POST"])
def upload_files():
    """Upload music files via drag-and-drop.

    Receives files with their relative paths preserved. Files are saved
    into a temporary directory that can then be passed to start_import.
    The relative directory structure from the browser is preserved.
    """
    if "files" not in flask.request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = flask.request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    # Create a temp directory to store uploaded files.
    upload_dir = tempfile.mkdtemp(prefix="beets_import_")

    saved = 0
    for f in files:
        # The relative path is sent via the webkitRelativePath-based
        # form field name, or as a "paths" form field.
        relative_path = f.filename
        if not relative_path:
            continue

        # Sanitize: prevent path traversal.
        # Normalize and reject any component that is ".." or starts with "/".
        parts = relative_path.replace("\\", "/").split("/")
        safe_parts = [p for p in parts if p and p != ".."]
        if not safe_parts:
            continue

        dest = os.path.join(upload_dir, *safe_parts)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        f.save(dest)
        saved += 1

    if saved == 0:
        shutil.rmtree(upload_dir)
        return jsonify({"error": "No valid files uploaded"}), 400

    return jsonify({"path": upload_dir, "files_saved": saved})


# ----------------------------- Plugin Class -------------------------------- #


class WebImportPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "host": "127.0.0.1",
                "port": 8338,
                "cors": "",
                "cors_supports_credentials": False,
                "reverse_proxy": False,
            }
        )

    def commands(self):
        cmd = ui.Subcommand(
            "webimport", help="start a web interface for importing music"
        )
        cmd.parser.add_option(
            "-d",
            "--debug",
            action="store_true",
            default=False,
            help="debug mode",
        )

        def func(lib, opts, args):
            if args:
                self.config["host"] = args.pop(0)
            if args:
                self.config["port"] = int(args.pop(0))

            app.config["lib"] = lib
            app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

            # Enable CORS if configured.
            if self.config["cors"]:
                self._log.info(
                    "Enabling CORS with origin: {}", self.config["cors"]
                )
                from flask_cors import CORS

                app.config["CORS_ALLOW_HEADERS"] = "Content-Type"
                app.config["CORS_RESOURCES"] = {
                    r"/*": {"origins": self.config["cors"].get(str)}
                }
                CORS(
                    app,
                    supports_credentials=self.config[
                        "cors_supports_credentials"
                    ].get(bool),
                )

            if self.config["reverse_proxy"]:
                from beetsplug.web import ReverseProxied

                app.wsgi_app = ReverseProxied(app.wsgi_app)

            self._log.info(
                "Starting web import interface at http://{}:{}/",
                self.config["host"].as_str(),
                self.config["port"].get(int),
            )
            app.run(
                host=self.config["host"].as_str(),
                port=self.config["port"].get(int),
                debug=opts.debug,
                threaded=True,
            )

        cmd.func = func
        return [cmd]
