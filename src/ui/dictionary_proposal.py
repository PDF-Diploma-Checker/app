"""Word-only submission from a linguistic error marker, off the GUI thread."""
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox
from common import shared_dictionary

TEXT = {
    'en': ('Propose a correct word', 'Enter a valid word for the shared dictionary. Only this word is sent. An administrator must approve it before it is used in future analyses.', 'Send for review', 'Submitting…', 'Pending administrator review.', 'This word is already approved. It will be synchronized before the next analysis.', 'This word was rejected by an administrator.', 'Submission failed. Check the service configuration or connection and try again.'),
    'pl': ('Zaproponuj poprawne słowo', 'Wpisz poprawne słowo do wspólnego słownika. Wysyłane jest tylko to słowo. Administrator musi je zatwierdzić przed użyciem w kolejnych analizach.', 'Wyślij do weryfikacji', 'Wysyłanie…', 'Oczekuje na zatwierdzenie administratora.', 'To słowo jest już zatwierdzone. Zostanie zsynchronizowane przed kolejną analizą.', 'Administrator odrzucił to słowo.', 'Nie udało się wysłać. Sprawdź konfigurację usługi lub połączenie i spróbuj ponownie.'),
}


PRIVACY_TEXT = {
    'pl': 'Wysyłanie jest dobrowolne. Analiza pracy pozostaje lokalna. Serwer otrzyma wpisany wyraz i dane połączenia (np. adres IP), bez PDF-u, zdania, obrazów ani logów. Zatwierdzony wyraz będzie dostępny we wspólnym słowniku dla innych użytkowników.',
    'en': 'Submission is optional. Thesis analysis stays local. The service receives the entered word and connection data (such as your IP address), without the PDF, sentence, images or logs. Approved words become available to other users in the shared dictionary.',
}
CONSENT_TEXT = {
    'pl': 'Chcę dobrowolnie wysłać ten wyraz do wspólnego słownika.',
    'en': 'I choose to submit this word to the shared dictionary.',
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
        self.submitted = False
        self.worker = None
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
        privacy = QLabel(PRIVACY_TEXT.get(lang, PRIVACY_TEXT['pl']))
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        try:
            endpoint = shared_dictionary.service_url()
        except ValueError:
            endpoint = 'usługa nie jest jeszcze skonfigurowana' if lang == 'pl' else 'service is not configured yet'
        recipient = QLabel(('Odbiorca: ' if lang == 'pl' else 'Recipient: ') + endpoint)
        recipient.setTextFormat(Qt.PlainText)
        recipient.setWordWrap(True)
        layout.addWidget(recipient)
        self.consent = QCheckBox(CONSENT_TEXT.get(lang, CONSENT_TEXT['pl']))
        self.consent.setChecked(False)
        self.consent.toggled.connect(self.update_send)
        layout.addWidget(self.consent)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.send = QPushButton(self.text[2])
        self.send.clicked.connect(self.submit)
        layout.addWidget(self.send)
        self.update_send()

    def update_send(self):
        busy = self.worker is not None and self.worker.isRunning()
        self.send.setEnabled(self.consent.isChecked() and not self.submitted and not busy)

    def submit(self):
        if not self.consent.isChecked() or self.submitted or (self.worker and self.worker.isRunning()):
            return
        try:
            word = shared_dictionary.normalize_word(self.word.text())
            shared_dictionary.service_url()
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.send.setEnabled(False)
        self.word.setEnabled(False)
        self.consent.setEnabled(False)
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
        self.update_send()
        self.word.setEnabled(not self.submitted)
        self.consent.setEnabled(not self.submitted)

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
