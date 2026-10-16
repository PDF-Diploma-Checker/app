"""JSON-backed index of the documents the user has opened."""

import datetime
import json
import logging
import os
import shutil

from common.path import INDEX_PATH

logger = logging.getLogger(__name__)

# Older versions kept the index in ~/DiplomaChecker on Linux/macOS.
_LEGACY_UNIX_PATH = os.path.join(os.path.expanduser("~"), "DiplomaChecker", "index.json")


class SavingFiles:
    """A class used to manage a JSON-based file index."""

    def __init__(self, index_path=None):
        self.index_path = str(INDEX_PATH) if index_path is None else str(index_path)
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)

        if index_path is None:
            self._migrate_legacy_index()

        self.data = self._load_index()

    def _migrate_legacy_index(self):
        """Copy the index from the old Linux/macOS location on first run."""
        if os.name == "nt" or os.path.exists(self.index_path):
            return
        if os.path.isfile(_LEGACY_UNIX_PATH):
            try:
                shutil.copy2(_LEGACY_UNIX_PATH, self.index_path)
                logger.info("Migrated index.json from %s", _LEGACY_UNIX_PATH)
            except OSError:
                logger.exception("Could not migrate legacy index.json")

    def _load_index(self):
        """Load the index from disk. Creates a new one if the file is missing or corrupt."""
        if not os.path.exists(self.index_path) or os.path.getsize(self.index_path) == 0:
            return self._create_initial_index()

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("index.json root is not an object")
        except (OSError, ValueError) as e:
            logger.error("Error reading %s: %r", self.index_path, e)
            self._backup_corrupt_index()
            return self._create_initial_index()

        if not isinstance(data.get("documents"), list):
            data["documents"] = []
        if not isinstance(data.get("rule_configurations"), list):
            data["rule_configurations"] = []
        return data

    def _backup_corrupt_index(self):
        """Keep the unreadable file as index.json.bak instead of silently overwriting it."""
        try:
            os.replace(self.index_path, self.index_path + ".bak")
        except OSError:
            logger.exception("Could not back up corrupt index.json")

    def _create_initial_index(self):
        """Create and save a basic, empty index structure."""
        initial_data = {"documents": [], "rule_configurations": []}
        self._save_to_disk(initial_data)
        return initial_data

    def _save_to_disk(self, data):
        """Write the index atomically (temp file + replace) so a crash can't corrupt it."""
        tmp_path = self.index_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self.index_path)
        except OSError:
            logger.exception("Error writing %s", self.index_path)

    def add_document(self, name, path, document_type="PDF"):
        """Add a document unless one with the same path already exists."""
        if any(doc.get("local_path") == path for doc in self.data["documents"]):
            return

        new_entry = {
            "file_name": name,
            "local_path": path,
            "type": document_type,
            "date_added": datetime.date.today().strftime("%Y-%m-%d"),
            "comments": [],
        }
        self.data["documents"].append(new_entry)
        self._save_to_disk(self.data)

    def delete_document(self, path):
        """Remove a document from the index and update the file on disk."""
        self.data["documents"] = [
            doc for doc in self.data["documents"] if doc.get("local_path") != path
        ]
        self._save_to_disk(self.data)

    def _find(self, path):
        for doc in self.data["documents"]:
            if doc.get("local_path") == path:
                return doc
        return None

    def save_comment(self, path, comment_data):
        """Append a comment to the document with the given path."""
        doc = self._find(path)
        if doc is None:
            return
        doc.setdefault("comments", []).append(comment_data)
        self._save_to_disk(self.data)

    def get_comments(self, path):
        """Return the comments assigned to the document."""
        doc = self._find(path)
        return doc.get("comments", []) if doc else []

    def save_errors(self, path, errors):
        """Save the list of errors detected during analysis of the document."""
        doc = self._find(path)
        if doc is None:
            return
        doc["analysis_errors"] = errors
        self._save_to_disk(self.data)

    def get_errors(self, path):
        """Return the analysis errors assigned to the document."""
        doc = self._find(path)
        return doc.get("analysis_errors", []) if doc else []

    def save_ai_result(self, path, sota_data):
        """Save the AI/report results for the document."""
        doc = self._find(path)
        if doc is None:
            return
        doc["sota_result"] = sota_data
        self._save_to_disk(self.data)