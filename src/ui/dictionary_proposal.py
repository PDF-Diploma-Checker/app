"""Word-only submission from a linguistic error marker, off the GUI thread."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton
from common import shared_dictionary

TEXT = {
    'en': ('Propose a correct word', 'Enter a valid word for the shared dictionary. Only this word is sent. An administrator must approve it before it is used in future analyses.', 'Send for review', 'Submitting…', 'Pending administrator review.', 'This word is already approved. It will be synchronized before the next analysis.', 'This word was rejected by an administrator.', 'Submission failed. Check the service configuration or connection and try again.'),
    'pl': ('Zaproponuj poprawne słowo', 'Wpisz poprawne słowo do wspólnego słownika. Wysyłane jest tylko to słowo. Administrator musi je zatwierdzić przed użyciem w kolejnych analizach.', 'Wyślij do weryfikacji', 'Wysyłanie…', 'Oczekuje na zatwierdzenie administratora.', 'To słowo jest już zatwierdzone. Zostanie zsynchronizowane przed kolejną analizą.', 'Administrator odrzucił to słowo.', 'Nie udało się wysłać. Sprawdź konfigurację usługi lub połączenie i spróbuj ponownie.'),
}


class ProposalWorker(QThread):
    result = Signal(str)

    def __init__(self, word, parent):
        super().__init__(parent)
        self.word = word

    def run(self):
        try:
            self.result.emit(shared_dictionary.propose(self.word))
        except Exception:
            self.result.emit('failed')


class ProposalDialog(QDialog):
    def __init__(self, parent=None, lang='pl'):
        super().__init__(parent)
        self.text = TEXT.get(lang, TEXT['pl'])
        self.setWindowTitle(self.text[0])
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        info = QLabel(self.text[1])
        info.setWordWrap(True)
        layout.addWidget(info)
        # Deliberately empty: findings can contain a complete thesis sentence.
        self.word = QLineEdit()
        self.word.setMaxLength(80)
        layout.addWidget(self.word)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.send = QPushButton(self.text[2])
        self.send.clicked.connect(self.submit)
        layout.addWidget(self.send)
        self.worker = None

    def submit(self):
        try:
            word = shared_dictionary.normalize_word(self.word.text())
            shared_dictionary.service_url()
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.send.setEnabled(False)
        self.word.setEnabled(False)
        self.status.setText(self.text[3])
        self.worker = ProposalWorker(word, self)
        self.worker.result.connect(self.show_result)
        self.worker.finished.connect(self.finished_submission)
        self.worker.start()

    def show_result(self, status):
        self.submitted = status != 'failed'
        index = {'pending': 4, 'approved': 5, 'rejected': 6}.get(status, 7)
        self.status.setText(self.text[index])

    def finished_submission(self):
        self.send.setEnabled(not getattr(self, 'submitted', False))
        self.word.setEnabled(not getattr(self, 'submitted', False))

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
