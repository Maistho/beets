/* Beets Web Import - Frontend Application */

let currentSessionId = null;
let polling = false;
let currentQuestion = null;

/* ----------------------------- Import Start ------------------------------- */

function startImport() {
    const pathInput = document.getElementById("import-path");
    const path = pathInput.value.trim();
    if (!path) {
        alert("Please enter a path to import.");
        return;
    }

    const startBtn = document.getElementById("start-btn");
    startBtn.disabled = true;

    fetch("/api/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({paths: [path]}),
    })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                alert("Error: " + data.error);
                startBtn.disabled = false;
                return;
            }
            currentSessionId = data.session_id;
            document.getElementById("start-panel").classList.add("hidden");
            document.getElementById("progress-panel").classList.remove("hidden");
            setStatus("Import started for: " + path, "running");
            addLog("Import started for: " + path, "info");
            pollForQuestions();
        })
        .catch(function(err) {
            alert("Failed to start import: " + err);
            startBtn.disabled = false;
        });
}

/* Handle Enter key in path input */
document.getElementById("import-path").addEventListener("keydown", function(e) {
    if (e.key === "Enter") startImport();
});

/* ----------------------------- Polling ------------------------------------- */

function pollForQuestions() {
    if (!currentSessionId) return;
    polling = true;

    fetch("/api/session/" + currentSessionId + "/question")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            handleMessage(data);
            if (polling && data.type !== "done") {
                pollForQuestions();
            }
        })
        .catch(function() {
            /* Network error - retry after a delay */
            if (polling) {
                setTimeout(pollForQuestions, 2000);
            }
        });
}

function handleMessage(msg) {
    switch (msg.type) {
        case "choose_match":
            showChooseMatch(msg);
            break;
        case "choose_item":
            showChooseItem(msg);
            break;
        case "resolve_duplicate":
            showResolveDuplicate(msg);
            break;
        case "should_resume":
            showShouldResume(msg);
            break;
        case "done":
            handleDone(msg);
            break;
        case "waiting":
            setStatus("Working...", "running");
            break;
    }
}

/* ----------------------------- Answer Submission -------------------------- */

function sendAnswer(answer) {
    if (!currentSessionId) return;

    var qa = document.getElementById("question-area");
    qa.classList.add("hidden");
    qa.innerHTML = "";
    setStatus("Processing...", "running");

    fetch("/api/session/" + currentSessionId + "/answer", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(answer),
    });
}

/* ----------------------------- UI Builders -------------------------------- */

function setStatus(text, type) {
    var el = document.getElementById("status-text");
    el.textContent = text;
    el.className = type ? ("status-" + type) : "";
}

function addLog(text, type) {
    var container = document.getElementById("log-messages");
    var entry = document.createElement("div");
    entry.className = "log-entry log-" + (type || "info");
    entry.textContent = text;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}

function simClass(similarity) {
    if (similarity >= 90) return "sim-high";
    if (similarity >= 70) return "sim-medium";
    return "sim-low";
}

function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* ----------------------------- Choose Match -------------------------------- */

function showChooseMatch(msg) {
    currentQuestion = msg;
    var task = msg.task;
    var candidates = msg.candidates;
    var rec = msg.recommendation;

    var pathsText = task.paths.join(", ");
    setStatus("Waiting for decision: " + pathsText, "running");

    var html = "<h3>Album Match</h3>";
    html += '<div class="task-info">';
    html += '<div>Path: <span class="path">' + escapeHtml(pathsText) + "</span></div>";
    html += "<div>Current: <strong>" + escapeHtml(task.cur_artist || "") + " - " + escapeHtml(task.cur_album || "") + "</strong>";
    html += " (" + task.num_items + " items)</div>";
    html += "<div>Recommendation: <strong>" + escapeHtml(rec) + "</strong></div>";
    html += "</div>";

    if (candidates.length > 0) {
        html += '<ul class="candidate-list">';
        for (var i = 0; i < candidates.length; i++) {
            var c = candidates[i];
            var sc = simClass(c.similarity);
            html += '<li onclick="selectCandidate(' + i + ', this)" data-index="' + i + '">';
            html += '<div class="candidate-meta">';
            html += '<span class="candidate-name">' + (i + 1) + ". " + escapeHtml(c.artist) + " - " + escapeHtml(c.name || c.album || "") + "</span>";
            html += '<span class="candidate-similarity ' + sc + '">' + c.similarity + "%</span>";
            html += "</div>";

            var details = [];
            if (c.year) details.push("Year: " + c.year);
            if (c.label) details.push("Label: " + c.label);
            if (c.data_source) details.push("Source: " + c.data_source);
            if (c.num_tracks) details.push(c.num_tracks + " tracks");
            if (details.length > 0) {
                html += '<div class="candidate-details">' + escapeHtml(details.join(" · ")) + "</div>";
            }

            var penalties = Object.keys(c.penalties || {});
            if (penalties.length > 0) {
                html += '<div class="candidate-penalties">Penalties: ' + escapeHtml(penalties.join(", ")) + "</div>";
            }
            html += "</li>";
        }
        html += "</ul>";
    } else {
        html += "<p>No matching releases found.</p>";
    }

    html += '<div class="action-buttons">';
    if (candidates.length > 0) {
        html += '<button onclick="applySelected()">Apply Selected</button>';
    }
    html += '<button class="secondary" onclick="sendAnswer({action:\'asis\'})">Use As-Is</button>';
    html += '<button class="secondary" onclick="sendAnswer({action:\'skip\'})">Skip</button>';
    html += '<button class="secondary" onclick="sendAnswer({action:\'tracks\'})">As Tracks</button>';
    html += '<button class="secondary" onclick="toggleSearch()">Search...</button>';
    html += "</div>";

    html += '<div id="search-panel" class="hidden search-form">';
    html += '<input type="text" id="search-artist" placeholder="Artist">';
    html += '<input type="text" id="search-name" placeholder="Album">';
    html += '<div class="search-form-buttons">';
    html += '<button onclick="doSearch()">Search</button>';
    html += '<input type="text" id="search-id" placeholder="MusicBrainz Release ID">';
    html += '<button onclick="doSearchId()">Search by ID</button>';
    html += "</div></div>";

    var qa = document.getElementById("question-area");
    qa.innerHTML = html;
    qa.classList.remove("hidden");

    /* Auto-select first candidate */
    if (candidates.length > 0) {
        var first = qa.querySelector('.candidate-list li[data-index="0"]');
        if (first) first.classList.add("selected");
    }
}

/* ----------------------------- Choose Item -------------------------------- */

function showChooseItem(msg) {
    currentQuestion = msg;
    var task = msg.task;
    var candidates = msg.candidates;
    var rec = msg.recommendation;

    var pathText = task.item_path || task.paths.join(", ");
    setStatus("Waiting for decision: " + pathText, "running");

    var html = "<h3>Track Match</h3>";
    html += '<div class="task-info">';
    html += '<div>Path: <span class="path">' + escapeHtml(pathText) + "</span></div>";
    html += "<div>Current: <strong>" + escapeHtml(task.cur_artist || "") + " - " + escapeHtml(task.cur_title || "") + "</strong></div>";
    html += "<div>Recommendation: <strong>" + escapeHtml(rec) + "</strong></div>";
    html += "</div>";

    if (candidates.length > 0) {
        html += '<ul class="candidate-list">';
        for (var i = 0; i < candidates.length; i++) {
            var c = candidates[i];
            var sc = simClass(c.similarity);
            html += '<li onclick="selectCandidate(' + i + ', this)" data-index="' + i + '">';
            html += '<div class="candidate-meta">';
            html += '<span class="candidate-name">' + (i + 1) + ". " + escapeHtml(c.artist) + " - " + escapeHtml(c.name || c.title || "") + "</span>";
            html += '<span class="candidate-similarity ' + sc + '">' + c.similarity + "%</span>";
            html += "</div>";
            if (c.data_source) {
                html += '<div class="candidate-details">Source: ' + escapeHtml(c.data_source) + "</div>";
            }
            html += "</li>";
        }
        html += "</ul>";
    } else {
        html += "<p>No matching recordings found.</p>";
    }

    html += '<div class="action-buttons">';
    if (candidates.length > 0) {
        html += '<button onclick="applySelected()">Apply Selected</button>';
    }
    html += '<button class="secondary" onclick="sendAnswer({action:\'asis\'})">Use As-Is</button>';
    html += '<button class="secondary" onclick="sendAnswer({action:\'skip\'})">Skip</button>';
    html += '<button class="secondary" onclick="toggleSearch()">Search...</button>';
    html += "</div>";

    html += '<div id="search-panel" class="hidden search-form">';
    html += '<input type="text" id="search-artist" placeholder="Artist">';
    html += '<input type="text" id="search-name" placeholder="Track title">';
    html += '<div class="search-form-buttons">';
    html += '<button onclick="doSearch()">Search</button>';
    html += '<input type="text" id="search-id" placeholder="MusicBrainz Recording ID">';
    html += '<button onclick="doSearchId()">Search by ID</button>';
    html += "</div></div>";

    var qa = document.getElementById("question-area");
    qa.innerHTML = html;
    qa.classList.remove("hidden");

    if (candidates.length > 0) {
        var first = qa.querySelector('.candidate-list li[data-index="0"]');
        if (first) first.classList.add("selected");
    }
}

/* ----------------------------- Duplicate Resolution ----------------------- */

function showResolveDuplicate(msg) {
    var task = msg.task;
    var dups = msg.duplicates;

    setStatus("Duplicate found - waiting for decision", "running");
    addLog("Duplicate detected for: " + task.paths.join(", "), "skip");

    var html = "<h3>Duplicate Found</h3>";
    html += '<div class="task-info">';
    html += "<div>This " + (msg.is_album ? "album" : "item") + " is already in your library!</div>";
    html += "</div>";

    html += '<div class="duplicate-info">';
    for (var i = 0; i < dups.length; i++) {
        var d = dups[i];
        html += '<div class="duplicate-item">';
        if (d.type === "album") {
            html += "<strong>Old:</strong> " + escapeHtml(d.artist || "") + " - " + escapeHtml(d.album || "");
            html += " (" + d.num_items + " items)";
        } else {
            html += "<strong>Old:</strong> " + escapeHtml(d.artist || "") + " - " + escapeHtml(d.title || "");
        }
        html += "</div>";
    }
    html += "</div>";

    html += '<div class="action-buttons">';
    html += '<button class="secondary" onclick="sendAnswer({action:\'skip\'})">Skip New</button>';
    html += '<button class="secondary" onclick="sendAnswer({action:\'keep\'})">Keep Both</button>';
    html += '<button class="secondary" onclick="sendAnswer({action:\'remove\'})">Remove Old</button>';
    html += '<button class="secondary" onclick="sendAnswer({action:\'merge\'})">Merge</button>';
    html += "</div>";

    var qa = document.getElementById("question-area");
    qa.innerHTML = html;
    qa.classList.remove("hidden");
}

/* ----------------------------- Resume Prompt ------------------------------ */

function showShouldResume(msg) {
    setStatus("Interrupted import detected", "running");

    var html = "<h3>Resume Import?</h3>";
    html += '<div class="task-info">';
    html += '<div>Import of <span class="path">' + escapeHtml(msg.path) + "</span> was interrupted.</div>";
    html += "<div>Do you want to resume?</div>";
    html += "</div>";

    html += '<div class="action-buttons">';
    html += '<button onclick="sendAnswer({resume:true})">Resume</button>';
    html += '<button class="secondary" onclick="sendAnswer({resume:false})">Start Over</button>';
    html += "</div>";

    var qa = document.getElementById("question-area");
    qa.innerHTML = html;
    qa.classList.remove("hidden");
}

/* ----------------------------- Done --------------------------------------- */

function handleDone(msg) {
    polling = false;
    var status = msg.status || "completed";
    if (status === "completed") {
        setStatus("Import completed successfully!", "completed");
        addLog("Import completed.", "action");
    } else {
        setStatus("Import finished with errors.", "error");
        addLog("Import finished with status: " + status, "error");
    }

    document.getElementById("question-area").classList.add("hidden");
    document.getElementById("progress-title").textContent = "Import Complete";

    /* Show button to start a new import */
    var qa = document.getElementById("question-area");
    qa.innerHTML = '<div class="action-buttons"><button onclick="resetUI()">Start New Import</button></div>';
    qa.classList.remove("hidden");
}

/* ----------------------------- Candidate Selection ------------------------ */

function selectCandidate(index, el) {
    var items = el.parentNode.querySelectorAll("li");
    for (var i = 0; i < items.length; i++) {
        items[i].classList.remove("selected");
    }
    el.classList.add("selected");
}

function applySelected() {
    var selected = document.querySelector(".candidate-list li.selected");
    if (!selected) {
        alert("Please select a candidate first.");
        return;
    }
    var index = parseInt(selected.getAttribute("data-index"), 10);
    addLog("Applied candidate #" + (index + 1), "action");
    sendAnswer({action: "apply", candidate_index: index});
}

/* ----------------------------- Search ------------------------------------- */

function toggleSearch() {
    var panel = document.getElementById("search-panel");
    if (panel.classList.contains("hidden")) {
        panel.classList.remove("hidden");
    } else {
        panel.classList.add("hidden");
    }
}

function doSearch() {
    var artist = document.getElementById("search-artist").value.trim();
    var name = document.getElementById("search-name").value.trim();
    if (!artist && !name) {
        alert("Please enter search terms.");
        return;
    }
    addLog("Searching for: " + artist + " - " + name, "info");
    sendAnswer({action: "search", artist: artist, name: name});
}

function doSearchId() {
    var id = document.getElementById("search-id").value.trim();
    if (!id) {
        alert("Please enter a MusicBrainz ID.");
        return;
    }
    addLog("Searching by ID: " + id, "info");
    sendAnswer({action: "search_id", id: id});
}

/* ----------------------------- Reset -------------------------------------- */

function resetUI() {
    currentSessionId = null;
    currentQuestion = null;
    polling = false;

    document.getElementById("start-panel").classList.remove("hidden");
    document.getElementById("progress-panel").classList.add("hidden");
    document.getElementById("question-area").classList.add("hidden");
    document.getElementById("question-area").innerHTML = "";
    document.getElementById("log-messages").innerHTML = "";
    document.getElementById("progress-title").textContent = "Importing...";
    document.getElementById("import-path").value = "";
    document.getElementById("start-btn").disabled = false;
}
