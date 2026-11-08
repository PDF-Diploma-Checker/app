"""Exceptions of the update code (shared by common.updater and common.delta; no other imports)."""


class UpdateError(Exception):
    """An update step failed. `code` selects the message shown to the user; `params` fill it in."""

    def __init__(self, code, **params):
        super().__init__(f"{code} {params}")
        self.code = code
        self.params = params


class UpdateCancelled(Exception):
    pass
