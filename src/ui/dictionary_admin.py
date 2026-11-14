"""Explicit admin application mode; credentials stay in memory and requests run on workers."""
import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QListWidget)
from common.shared_dictionary import service_url


class AdminWorker(QThread):
    result = Signal(object, str)

    def __init__(self, user, password, review=None, parent=None):
        super().__init__(parent)
        self.credentials = (user, password)
        self.review = review

    def run(self):
        try:
            url = service_url()
            if self.review is not None:
                response = requests.post(url + '/admin/review', auth=self.credentials,
                                         headers={'X-Dictionary-Review': '1'}, json=self.review,
                                         timeout=(3, 10), allow_redirects=False)
                if response.status_code != 200:
                    raise ValueError(f'Review failed ({response.status_code}). Refresh before retrying.')
            response = requests.get(url + '/admin/queue', auth=self.credentials,
                                    timeout=(3, 10), allow_redirects=False)
            if response.status_code != 200:
                raise ValueError(f'Queue unavailable ({response.status_code}). Check credentials and service configuration.')
            rows = response.json()
            if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(row, dict) or type(row.get('id')) is not int or not isinstance(row.get('word'), str) for row in rows):
                raise ValueError('Invalid queue response')
            self.result.emit(rows, '')
        except ValueError as error:
            self.result.emit(None, str(error))
        except requests.RequestException:
            self.result.emit(None, 'Connection failed. Refresh the queue before retrying; a submitted decision may already be saved.')
        finally:
            self.credentials = None


class AdminDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Shared dictionary — administrator')
        self.resize(600, 480)
        self.worker = None
        self.rows = []
        self.loaded = False
        layout = QVBoxLayout(self)
        info = QLabel('Sign in to the configured dictionary service. Credentials are kept only in memory. Review valid words before approving them for all clients.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.user = QLineEdit()
        self.user.setPlaceholderText('Administrator username')
        self.password = QLineEdit()
        self.password.setPlaceholderText('Administrator password')
        self.password.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.user)
        layout.addWidget(self.password)
        self.refresh = QPushButton('Sign in / refresh queue')
        self.refresh.clicked.connect(lambda: self.request())
        layout.addWidget(self.refresh)
        self.queue = QListWidget()
        self.queue.currentRowChanged.connect(self.update_buttons)
        layout.addWidget(self.queue)
        buttons = QHBoxLayout()
        self.approve = QPushButton('Approve')
        self.reject_button = QPushButton('Reject')
        self.approve.clicked.connect(lambda: self.review('approved'))
        self.reject_button.clicked.connect(lambda: self.review('rejected'))
        buttons.addWidget(self.approve)
        buttons.addWidget(self.reject_button)
        layout.addLayout(buttons)
        self.status = QLabel('Sign in to load pending word proposals.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.user.textChanged.connect(self.invalidate)
        self.password.textChanged.connect(self.invalidate)
        self.update_buttons()

    def invalidate(self):
        self.loaded = False
        self.queue.clear()
        self.rows = []
        self.update_buttons()

    def update_buttons(self, *_):
        busy = self.worker is not None and self.worker.isRunning()
        selected = self.loaded and 0 <= self.queue.currentRow() < len(self.rows)
        self.approve.setEnabled(selected and not busy)
        self.reject_button.setEnabled(selected and not busy)

    def review(self, decision):
        index = self.queue.currentRow()
        if self.loaded and 0 <= index < len(self.rows):
            self.request({'id': self.rows[index]['id'], 'decision': decision})

    def request(self, review=None):
        if self.worker and self.worker.isRunning():
            return
        if not self.user.text() or not self.password.text():
            self.status.setText('Enter administrator credentials.')
            return
        self.loaded = False
        self.status.setText('Contacting dictionary service…')
        self.refresh.setEnabled(False)
        self.user.setEnabled(False)
        self.password.setEnabled(False)
        self.worker = AdminWorker(self.user.text(), self.password.text(), review, self)
        self.worker.result.connect(self.show_result)
        self.worker.finished.connect(self.finished_request)
        self.worker.start()
        self.update_buttons()

    def show_result(self, rows, error):
        self.queue.clear()
        self.rows = rows or []
        self.loaded = not error
        if error:
            self.status.setText(error)
        else:
            for row in self.rows:
                self.queue.addItem(f"{row['word']} — {row.get('created', '')}")
            self.status.setText(f'{len(self.rows)} pending (oldest first, up to 200). Decisions are final.')
        self.update_buttons()

    def finished_request(self):
        self.refresh.setEnabled(True)
        self.user.setEnabled(True)
        self.password.setEnabled(True)
        self.update_buttons()

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            self.password.clear()
            super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            self.password.clear()
            super().closeEvent(event)


def launch():
    import sys
    from PySide6.QtWidgets import QApplication
    from ui import styles
    app = QApplication.instance() or QApplication(sys.argv)
    styles.apply_global_style(app)
    dialog = AdminDialog()
    dialog.show()
    return app.exec()
