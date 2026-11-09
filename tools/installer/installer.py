"""The window of the installer: choose a version and a folder, then wait. Built by tools/installer/build.py.

Plain tkinter, so the file stays about 20 MB; the colours are those of the app (ui/styles.py).
"""

import logging
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox

import install_core as core
from common.update_errors import UpdateCancelled, UpdateError

logger = logging.getLogger(__name__)

POLL_MS = 100
WIDTH = 600
LOGO_HEIGHT = 44
BG = "#F8FAFC"
SURFACE = "#FFFFFF"
BORDER = "#E5E7EB"
TEXT = "#111827"
TEXT_2 = "#6B7280"
PRIMARY = "#1E8CFA"
PRIMARY_HOVER = "#1478DC"
PRIMARY_50 = "#F2F8FF"
PRIMARY_100 = "#DCEEFF"
SUCCESS = "#047A68"
SUCCESS_BG = "#E6FAF6"
SUCCESS_DOT = "#04C8A7"
DANGER = "#B91C1C"
DANGER_BG = "#FEF2F2"
NEUTRAL_BG = "#F3F4F6"
DISABLED = "#D1D5DB"

_TEXTS = {
    "pl": {
        "title": "Instalator DiplomaChecker",
        "subtitle": "Instalator",
        "looking": "Sprawdzam komputer i najnowszą wersję...",
        "version": "Instalator, wersja {version}",
        "gpu_found": "Wykryto kartę {name} ({vram:.0f} GB). Polecamy wersję GPU.",
        "gpu_none": "Nie wykryto karty NVIDIA. Polecamy wersję CPU.",
        "gpu": "GPU",
        "gpu_desc": "Tryb dokładny z AI na karcie NVIDIA. Najszybsza.",
        "cpu": "CPU",
        "cpu_desc": "Tryb dokładny z AI na procesorze.",
        "base": "Podstawowa",
        "base_desc": "Tylko tryb szybki, bez AI.",
        "recommended": "Polecana",
        "folder": "Folder instalacji",
        "browse": "Zmień",
        "desktop": "Dodaj skrót na pulpicie",
        "install": "Zainstaluj",
        "cancel": "Anuluj",
        "retry_button": "Spróbuj ponownie",
        "run": "Uruchom",
        "close": "Zamknij",
        "installing": "Instaluję wersję {variant}",
        "compare": "Sprawdzam pliki...",
        "download": "Pobrano {done} z {total}",
        "retry": "Serwer nie odpowiada, za chwilę spróbuję ponownie (próba {attempt} z {total}).",
        "finishing": "Kończę instalację...",
        "done_title": "Gotowe",
        "installed": "Zainstalowano wersję {version}.",
        "done": "DiplomaChecker jest w folderze {target}",
        "no_shortcut": "DiplomaChecker jest w folderze {target}. Nie udało się dodać skrótu.",
        "cancelled": "Przerwano. Pobrane pliki zostaną użyte przy następnej próbie.",
        "no_release": "Nie udało się odczytać najnowszej wersji. Sprawdź internet i spróbuj ponownie.",
        "space": "Za mało miejsca na dysku: potrzeba {needed}, wolne {free}.",
        "locked": "Nie można podmienić plików. Zamknij DiplomaChecker i spróbuj ponownie.",
        "failed": "Instalacja nie powiodła się ({error}). Pobrane pliki zostaną użyte przy następnej próbie.",
    },
    "en": {
        "title": "DiplomaChecker Installer",
        "subtitle": "Installer",
        "looking": "Checking this computer and the latest version...",
        "version": "Installer, version {version}",
        "gpu_found": "Found {name} ({vram:.0f} GB). We recommend the GPU version.",
        "gpu_none": "No NVIDIA card found. We recommend the CPU version.",
        "gpu": "GPU",
        "gpu_desc": "Detailed mode with AI on an NVIDIA card. The fastest.",
        "cpu": "CPU",
        "cpu_desc": "Detailed mode with AI on the processor.",
        "base": "Basic",
        "base_desc": "Fast mode only, no AI.",
        "recommended": "Recommended",
        "folder": "Install folder",
        "browse": "Change",
        "desktop": "Add a desktop shortcut",
        "install": "Install",
        "cancel": "Cancel",
        "retry_button": "Try again",
        "run": "Open",
        "close": "Close",
        "installing": "Installing the {variant} version",
        "compare": "Checking files...",
        "download": "Downloaded {done} of {total}",
        "retry": "The server is not answering, trying again shortly (attempt {attempt} of {total}).",
        "finishing": "Finishing the installation...",
        "done_title": "All done",
        "installed": "Version {version} is installed.",
        "done": "DiplomaChecker is in {target}",
        "no_shortcut": "DiplomaChecker is in {target}. The shortcut could not be added.",
        "cancelled": "Stopped. The downloaded files will be used on the next try.",
        "no_release": "Could not read the latest version. Check the internet connection and try again.",
        "space": "Not enough disk space: {needed} needed, {free} free.",
        "locked": "The files cannot be replaced. Close DiplomaChecker and try again.",
        "failed": "The installation failed ({error}). The downloaded files will be used on the next try.",
    },
}


def platform_name():
    return "windows" if sys.platform == "win32" else "linux"


def size_text(number):
    return f"{number / 1024 ** 3:.1f} GB" if number >= 1024 ** 3 else f"{number / 1024 ** 2:.0f} MB"


def error_text(texts, error):
    if isinstance(error, UpdateError) and error.code == "space":
        return texts["space"].format(needed=size_text(error.params["needed"]), free=size_text(error.params["free"]))
    if isinstance(error, UpdateError) and error.code in ("locked", "no_release"):
        return texts[error.code]
    return texts["failed"].format(error=getattr(error, "code", None) or error)


class Button(tk.Label):
    """A flat button: the native ones cannot be coloured the same way on every system."""

    def __init__(self, parent, text, command, font, primary=False):
        self.colors = (PRIMARY, PRIMARY_HOVER, "white") if primary else (NEUTRAL_BG, BORDER, TEXT)
        self.command, self.enabled = command, True
        super().__init__(parent, text=text, font=font, padx=20, pady=9, cursor="hand2",
                         bg=self.colors[0], fg=self.colors[2])
        self.bind("<Enter>", lambda _: self.enabled and self.config(bg=self.colors[1]))
        self.bind("<Leave>", lambda _: self.enabled and self.config(bg=self.colors[0]))
        self.bind("<Button-1>", lambda _: self.enabled and self.command())

    def set(self, text=None, command=None, enabled=True):
        if text:
            self.config(text=text)
        if command:
            self.command = command
        self.enabled = enabled
        self.config(bg=self.colors[0] if enabled else DISABLED, cursor="hand2" if enabled else "arrow")


class Card(tk.Frame):
    """One version to choose: the whole card is clickable."""

    def __init__(self, parent, fonts, title, description, size, badge, on_click):
        super().__init__(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER, padx=14, pady=10)
        self.dot = tk.Canvas(self, width=20, height=20, highlightthickness=0, bg=SURFACE, cursor="hand2")
        self.dot.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        top = tk.Frame(self, bg=SURFACE)
        top.grid(row=0, column=1, sticky="w")
        self.title = tk.Label(top, text=title, font=fonts["strong"], bg=SURFACE, fg=TEXT)
        self.title.pack(side="left")
        self.badge = None
        if badge:
            self.badge = tk.Label(top, text=badge, font=fonts["small"], bg=PRIMARY_100, fg=PRIMARY_HOVER, padx=7, pady=1)
            self.badge.pack(side="left", padx=(8, 0))
        self.description = tk.Label(self, text=description, font=fonts["small"], bg=SURFACE, fg=TEXT_2)
        self.description.grid(row=1, column=1, sticky="w")
        self.size = tk.Label(self, text=size, font=fonts["normal"], bg=SURFACE, fg=TEXT_2)
        self.size.grid(row=0, column=2, rowspan=2, padx=(12, 0))
        self.columnconfigure(1, weight=1)
        self.parts = [self, self.dot, top, self.title, self.description, self.size]
        for widget in (*self.parts, *([self.badge] if self.badge else [])):
            widget.bind("<Button-1>", lambda _: on_click())
            widget.config(cursor="hand2")

    def select(self, chosen):
        background = PRIMARY_50 if chosen else SURFACE
        for widget in self.parts:
            widget.config(bg=background)
        self.config(highlightbackground=PRIMARY if chosen else BORDER, highlightthickness=2 if chosen else 1,
                    padx=13 if chosen else 14, pady=9 if chosen else 10)
        self.dot.delete("all")
        self.dot.create_oval(2, 2, 18, 18, outline=PRIMARY if chosen else DISABLED, width=2)
        if chosen:
            self.dot.create_oval(6, 6, 14, 14, fill=PRIMARY, outline=PRIMARY)


class Bar(tk.Canvas):
    HEIGHT = 8

    def __init__(self, parent):
        super().__init__(parent, height=self.HEIGHT, width=WIDTH, highlightthickness=0, bg=PRIMARY_100)
        self.fill = self.create_rectangle(0, 0, 0, self.HEIGHT, fill=PRIMARY, width=0)

    def set(self, fraction):
        self.coords(self.fill, 0, 0, self.winfo_width() * fraction, self.HEIGHT)


class Installer:
    def __init__(self, root):
        self.root, self.texts = root, _TEXTS[core.language()]
        self.events, self.cancel_flag = queue.Queue(), threading.Event()
        self.info, self.target, self.selected, self.cards = None, None, None, {}
        self.folder, self.desktop = tk.StringVar(value=str(core.default_target())), tk.BooleanVar(value=True)
        family = "Segoe UI" if sys.platform == "win32" else tkfont.nametofont("TkDefaultFont").actual("family")
        self.fonts = {"title": (family, 17, "bold"), "strong": (family, 11, "bold"), "normal": (family, 10),
                      "small": (family, 9), "percent": (family, 30, "bold")}
        self.build()
        self.start(self.load)
        self.root.after(POLL_MS, self.poll)

    def label(self, parent, text="", font="normal", color=TEXT, **options):
        background = options.pop("bg", parent["bg"])
        return tk.Label(parent, text=text, font=self.fonts[font], fg=color, bg=background, justify="left",
                        wraplength=WIDTH, **options)

    def build(self):
        self.root.title(self.texts["title"])
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        outer = tk.Frame(self.root, bg=BG, padx=24, pady=20)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 14))
        logo = Path(getattr(sys, "_MEIPASS", ".")) / "logo.png"
        if logo.is_file():
            image = tk.PhotoImage(file=str(logo))
            self.logo = image.subsample(max(1, image.height() // LOGO_HEIGHT))
            tk.Label(header, image=self.logo, bg=BG).pack(side="left", padx=(0, 12))
        names = tk.Frame(header, bg=BG)
        names.pack(side="left")
        self.label(names, "DiplomaChecker", "title").pack(anchor="w")
        self.subtitle = self.label(names, self.texts["subtitle"], "small", TEXT_2)
        self.subtitle.pack(anchor="w")

        self.notice = self.label(outer, self.texts["looking"], bg=NEUTRAL_BG, padx=12, pady=9, anchor="w")
        self.notice.pack(fill="x")

        self.stage = tk.Frame(outer, bg=BG, width=WIDTH)
        self.stage.pack(fill="both", expand=True, pady=(12, 16))
        self.build_choose()
        self.build_progress()

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x")
        self.secondary = Button(buttons, self.texts["close"], self.root.destroy, self.fonts["normal"])
        self.secondary.pack(side="right")
        self.primary = Button(buttons, self.texts["install"], self.begin, self.fonts["strong"], primary=True)
        self.primary.pack(side="right", padx=(0, 8))
        self.primary.set(enabled=False)
        self.show(self.choose)

    def build_choose(self):
        self.choose = tk.Frame(self.stage, bg=BG)
        self.card_list = tk.Frame(self.choose, bg=BG)
        self.card_list.pack(fill="x")
        self.label(self.choose, self.texts["folder"], "small", TEXT_2).pack(anchor="w", pady=(12, 3))
        row = tk.Frame(self.choose, bg=BG)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.folder, font=self.fonts["normal"], relief="flat", bg=SURFACE, fg=TEXT,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=PRIMARY,
                 insertbackground=TEXT).pack(side="left", fill="x", expand=True, ipady=7, ipadx=6)
        Button(row, self.texts["browse"], self.pick_folder, self.fonts["normal"]).pack(side="left", padx=(8, 0))
        if sys.platform == "win32":
            tk.Checkbutton(self.choose, text=self.texts["desktop"], variable=self.desktop, font=self.fonts["normal"],
                           bg=BG, fg=TEXT, activebackground=BG, highlightthickness=0, bd=0).pack(anchor="w", pady=(10, 0))

    def build_progress(self):
        self.progress = tk.Frame(self.stage, bg=BG)
        self.heading = self.label(self.progress, "", "strong")
        self.heading.pack(anchor="w", pady=(18, 0))
        self.percent = self.label(self.progress, "", "percent", PRIMARY)
        self.percent.pack(anchor="w", pady=(2, 8))
        self.bar = Bar(self.progress)
        self.bar.pack(fill="x")
        self.status = self.label(self.progress, "", "normal", TEXT_2)
        self.status.pack(anchor="w", pady=(10, 18))

    def show(self, page):
        for child in self.stage.winfo_children():
            child.pack_forget()
        page.pack(fill="both", expand=True)
        self.root.update_idletasks()

    def say(self, text, foreground=TEXT, background=NEUTRAL_BG):
        self.notice.config(text=text, fg=foreground, bg=background)

    def start(self, work):
        threading.Thread(target=work, daemon=True).start()

    def load(self):
        try:
            gpus = core.detect_gpus()
            info = core.latest_release()
            self.events.put(("loaded", info, gpus, core.variant_sizes(info, platform_name())))
        except Exception as e:
            logger.exception("Loading the release failed")
            self.events.put(("load_failed", e))

    def reload(self):
        self.say(self.texts["looking"])
        self.primary.set(self.texts["install"], self.begin, enabled=False)
        self.start(self.load)

    def show_choices(self, info, gpus, sizes):
        self.info = info
        recommended = core.recommended_variant(gpus)
        if recommended not in sizes:
            recommended = next(iter(sizes))
        self.subtitle.config(text=self.texts["version"].format(version=info["version"]))
        if gpus:
            self.say(self.texts["gpu_found"].format(name=gpus[0]["name"], vram=gpus[0]["vram_gb"]), SUCCESS, SUCCESS_BG)
        else:
            self.say(self.texts["gpu_none"])
        for variant in core.VARIANTS:
            if variant in sizes:
                self.cards[variant] = Card(self.card_list, self.fonts, self.texts[variant], self.texts[variant + "_desc"],
                                           size_text(sizes[variant]) if sizes[variant] else "",   # archives come later
                                           self.texts["recommended"] if variant == recommended else "",
                                           lambda v=variant: self.pick(v))
                self.cards[variant].pack(fill="x", pady=(0, 8))
        self.pick(recommended)
        self.primary.set(enabled=True)
        self.root.update_idletasks()
        self.root.geometry(f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}")   # the same for every step

    def pick(self, variant):
        self.selected = variant
        for name, card in self.cards.items():
            card.select(name == variant)

    def pick_folder(self):
        chosen = filedialog.askdirectory(initialdir=str(Path(self.folder.get()).parent))
        if chosen:
            self.folder.set(chosen)

    def begin(self):
        self.cancel_flag.clear()
        self.show(self.progress)
        self.say(self.texts["version"].format(version=self.info["version"]))
        self.heading.config(text=self.texts["installing"].format(variant=self.texts[self.selected]))
        self.percent.config(text="0%", fg=PRIMARY)
        self.bar.set(0)
        self.status.config(text="")
        self.primary.pack_forget()
        self.secondary.set(self.texts["cancel"], self.cancel_flag.set)
        self.target = core.resolve_target(self.folder.get())
        self.start(lambda: self.work(self.selected, self.target))

    def work(self, variant, target):
        try:
            core.install(self.info, variant, platform_name(), target,
                         lambda stage, done, total: self.events.put(("progress", stage, done, total)),
                         self.cancel_flag.is_set)
            self.events.put(("finishing",))
            self.events.put(("done", core.create_shortcuts(target, self.desktop.get())))
        except UpdateCancelled:
            self.events.put(("stopped", self.texts["cancelled"]))
        except Exception as e:
            logger.exception("The installation failed")
            self.events.put(("stopped", error_text(self.texts, e)))

    def show_progress(self, stage, done, total):
        if stage == "retry":
            self.status.config(text=self.texts["retry"].format(attempt=done, total=total))
            return
        fraction = done / (total or 1)
        self.bar.set(fraction)
        self.percent.config(text=f"{fraction:.0%}")
        self.status.config(text=self.texts["compare"] if stage == "compare" else self.texts["download"].format(
            done=size_text(done), total=size_text(total)))

    def finish(self, shortcut):
        self.bar.set(1)
        self.heading.config(text="")
        self.percent.config(text=self.texts["done_title"], fg=SUCCESS)
        self.status.config(text=self.texts["done" if shortcut else "no_shortcut"].format(target=self.target))
        self.say(self.texts["installed"].format(version=self.info["version"]), SUCCESS, SUCCESS_BG)
        self.show_primary(self.texts["run"], self.run_app)
        self.secondary.set(self.texts["close"], self.root.destroy)

    def stop(self, message):
        self.show(self.choose)
        self.say(message, DANGER, DANGER_BG)
        self.show_primary(self.texts["retry_button"], self.begin)
        self.secondary.set(self.texts["close"], self.root.destroy)

    def show_primary(self, text, command):
        self.primary.set(text, command)
        self.primary.pack(side="right", padx=(0, 8))

    def run_app(self):
        try:
            core.launch(self.target)
        except OSError as e:
            messagebox.showerror(self.texts["title"], str(e))
            return
        self.root.destroy()

    def poll(self):
        while not self.events.empty():
            kind, *args = self.events.get()
            if kind == "loaded":
                self.show_choices(*args)
            elif kind == "load_failed":
                self.say(error_text(self.texts, args[0]), DANGER, DANGER_BG)
                self.primary.set(self.texts["retry_button"], self.reload)
            elif kind == "progress":
                self.show_progress(*args)
            elif kind == "finishing":
                self.status.config(text=self.texts["finishing"])
            elif kind == "done":
                self.finish(*args)
            elif kind == "stopped":
                self.stop(*args)
        self.root.after(POLL_MS, self.poll)


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # sharp text on a scaled screen
    root = tk.Tk()
    logo = Path(getattr(sys, "_MEIPASS", ".")) / "logo.png"
    if logo.is_file():
        root.iconphoto(True, tk.PhotoImage(file=str(logo)))
    Installer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
