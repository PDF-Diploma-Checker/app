"""Word-only submission from a linguistic error marker, off the GUI thread."""
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QFrame, QHBoxLayout, QSizePolicy
from common import shared_dictionary
from . import styles

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
        self.lang = lang
        en = lang == 'en'
        self.setWindowTitle(self.text[0])
        self.setMinimumWidth(520)
        self.resize(560, 490)
        self.setStyleSheet(f"QDialog {{ background: {styles.BG}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        def label(text, color=styles.TEXT_2, size=13, bold=False):
            item = QLabel(text)
            item.setTextFormat(Qt.PlainText)
            item.setWordWrap(True)
            item.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            item.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {600 if bold else 400}; background: transparent;")
            return item

        layout.addWidget(label(self.text[0], styles.TEXT, 22, True))
        layout.addWidget(label('An administrator will review your word.' if en else 'Pomóż ulepszyć sprawdzanie pisowni. Administrator zweryfikuje zgłoszony wyraz.'))

        def card(name, background, border):
            box = QFrame()
            box.setObjectName(name)
            box.setStyleSheet(f"QFrame#{name} {{ background: {background}; border: 1px solid {border}; border-radius: 12px; }}")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(16, 14, 16, 14)
            inner.setSpacing(10)
            layout.addWidget(box)
            return inner

        fields = card('WordProposalForm', styles.SURFACE, styles.BORDER)
        fields.addWidget(label('Word to review' if en else 'Wyraz do weryfikacji', styles.TEXT, 14, True))
        # Never prefill a finding: it may contain an entire thesis sentence.
        self.word = QLineEdit()
        self.word.setMaxLength(80)
        self.word.setPlaceholderText('Enter one correctly spelled word' if en else 'Wpisz jeden poprawnie zapisany wyraz')
        self.word.setAccessibleName('Word to review' if en else 'Wyraz do weryfikacji')
        self.word.textChanged.connect(self.update_send)
        fields.addWidget(self.word)
        fields.addWidget(label('Only this word is submitted. Do not paste a sentence.' if en else 'Zgłaszasz tylko ten wyraz. Nie wklejaj całego zdania.', size=12))
        privacy = card('WordProposalPrivacy', styles.PRIMARY_50, styles.PRIMARY_200)
        privacy.addWidget(label('Your thesis stays on your computer' if en else 'Twoja praca pozostaje na komputerze', styles.TEXT, 13, True))
        privacy.addWidget(label(PRIVACY_TEXT.get(lang, PRIVACY_TEXT['pl']), size=12))
        try:
            endpoint = shared_dictionary.service_url()
        except ValueError:
            endpoint = 'service is not configured yet' if en else 'usługa nie jest jeszcze skonfigurowana'
        privacy.addWidget(label(('Recipient: ' if en else 'Odbiorca: ') + endpoint, size=11))
        self.consent = QCheckBox(CONSENT_TEXT.get(lang, CONSENT_TEXT['pl']))
        self.consent.setAccessibleName(CONSENT_TEXT.get(lang, CONSENT_TEXT['pl']))
        self.consent.setChecked(False)
        self.consent.toggled.connect(self.update_send)
        layout.addWidget(self.consent)
        self.status = label('')
        self.status.setAccessibleName('Submission status' if en else 'Stan zgłoszenia')
        layout.addWidget(self.status)
        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel = QPushButton('Cancel' if en else 'Anuluj')
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.cancel)
        self.send = QPushButton(self.text[2])
        self.send.setStyleSheet(styles.BLUE_BUTTON_STYLE)
        self.send.setAutoDefault(False)
        self.send.clicked.connect(self.submit)
        buttons.addWidget(self.send)
        layout.addLayout(buttons)
        self.update_send()

    def update_send(self):
        busy = self.worker is not None and self.worker.isRunning()
        try:
            shared_dictionary.normalize_word(self.word.text())
            valid = True
        except ValueError:
            valid = False
        self.send.setEnabled(valid and self.consent.isChecked() and not self.submitted and not busy)

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
        self.cancel.setEnabled(False)
        self.status.setStyleSheet(f"color: {styles.TEXT_2}; font-size: 13px;")
        self.status.setText(self.text[3])
        self.worker = ProposalWorker(word, self)
        self.worker.result.connect(self.show_result)
        self.worker.finished.connect(self.finished_submission)
        self.worker.start()

    def show_result(self, status):
        self.submitted = status != 'failed'
        index = {'pending': 4, 'approved': 5, 'rejected': 6}.get(status, 7)
        self.status.setText(self.text[index])
        color = styles.DANGER if status == "failed" else styles.WARNING if status == "rejected" else styles.SUCCESS
        self.status.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")

    def finished_submission(self):
        self.update_send()
        self.word.setEnabled(not self.submitted)
        self.consent.setEnabled(not self.submitted)
        self.cancel.setEnabled(True)
        if self.submitted:
            self.cancel.setText("Close" if self.lang == "en" else "Zamknij")

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
