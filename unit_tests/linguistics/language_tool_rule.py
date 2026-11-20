'''
Skrypt pomocniczy: dla podanego zdania pokazuje, którą regułą LanguageTool oznaczył błąd,
i gdzie ta reguła leży w źródłach LT (plik XML + numer linii), żeby dało się ją od razu znaleźć.

Uruchomienie (z katalogu app/):
    ..\\.venv\\Scripts\\python.exe unit_tests/linguistics/language_tool_rule.py "Dla 30% budżetu wyniki wariantów B, C i D uległy wyraźnemu zbliżeniu."
    ..\\.venv\\Scripts\\python.exe unit_tests/linguistics/language_tool_rule.py --lang en "This are a test."
    ..\\.venv\\Scripts\\python.exe unit_tests/linguistics/language_tool_rule.py            # tryb interaktywny: zdanie na linię, pusta linia kończy

Opcje:
    --lang pl|en   język tekstu (domyślnie pl),
    --raw          LanguageTool bez wyłączonych reguł z language_error_extractor.py
                   (domyślnie: ta sama konfiguracja co w aplikacji),
    --xml          wypisuje cały fragment XML reguły (podreguły) z grammar.xml.

Dla każdego trafienia wypisuje: rule_id, sub_id (numer podreguły w <rulegroup>), nazwę reguły, kategorię,
komunikat, znaleziony fragment, propozycje oraz plik:linia w lokalnym LanguageTool i link do GitHuba.
Reguły napisane w Javie (np. MORFOLOGIK_RULE_PL_PL) nie mają wpisu w XML - wtedy wypisywany jest link do wyszukiwarki.

To nie jest test jednostkowy (brak przedrostka test_), unittest discover go pomija.
'''
import argparse
import os
import re
import sys
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

LT_VERSION = "6.6"
LT_DIR_DEFAULT = Path(os.environ.get("APPDATA", "")) / "DiplomaChecker" / "LanguageTool" / f"LanguageTool-{LT_VERSION}"
JBR_BIN = Path(r"C:\Program Files\Android\Android Studio\jbr\bin")
GITHUB_BLOB = f"https://github.com/languagetool-org/languagetool/blob/v{LT_VERSION}/languagetool-language-modules"
GITHUB_SEARCH = "https://github.com/search?type=code&q="


def prepare_environment():
    '''Points language_tool_python at the local LT 6.6 and Java 21 (system java 1.8 cannot start LT).'''
    if "LTP_JAR_DIR_PATH" not in os.environ and LT_DIR_DEFAULT.is_dir():
        os.environ["LTP_JAR_DIR_PATH"] = str(LT_DIR_DEFAULT)
    if JBR_BIN.is_dir() and str(JBR_BIN) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(JBR_BIN) + os.pathsep + os.environ.get("PATH", "")


def get_tool(lang, raw):
    '''Returns a LanguageTool instance: the app's configured one, or a fresh one with no rules disabled.'''
    if raw:
        import language_tool_python
        return language_tool_python.LanguageTool("pl-PL" if lang == "pl" else "en-GB",
                                                 language_tool_download_version=LT_VERSION)
    from analysis.modules.linguistics import language_error_extractor as lee
    lee._init_language_tools()
    tool = lee._TOOL_PL if lang == "pl" else lee._TOOL_EN
    if tool is None:
        sys.exit("LanguageTool się nie uruchomił (sprawdź Javę >= 17 i LTP_JAR_DIR_PATH).")
    return tool


def check_raw(tool, text):
    '''Queries the LT server directly, because language_tool_python's Match drops rule subId, description and category name.'''
    url = urllib.parse.urljoin(tool._url, "check")
    return tool._query_server(url, tool._create_params(text))["matches"]


def rule_xml_files(lang):
    '''Grammar/style XML files of the language in the local LT directory.'''
    lt_dir = Path(os.environ.get("LTP_JAR_DIR_PATH", LT_DIR_DEFAULT))
    rules_dir = lt_dir / "org" / "languagetool" / "rules" / lang
    return sorted(p for p in rules_dir.rglob("*.xml") if p.name != "bitext.xml") if rules_dir.is_dir() else []


def find_rule(lang, rule_id, sub_id):
    '''Finds (file, line, xml_lines) of the rule; for a <rulegroup> it goes to the sub_id-th <rule> inside.'''
    start_re = re.compile(r'<(rulegroup|rule)\b[^>]*\bid="%s"' % re.escape(rule_id))
    for path in rule_xml_files(lang):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            found = start_re.search(line)
            if not found:
                continue
            if found.group(1) == "rulegroup" and sub_id:
                count = 0
                for j in range(i + 1, len(lines)):
                    if "</rulegroup>" in lines[j]:
                        break
                    if re.search(r"<rule\b", lines[j]):
                        count += 1
                        if count == int(sub_id):
                            return path, j + 1, element_lines(lines, j, "rule")
            return path, i + 1, element_lines(lines, i, found.group(1))
    return None


def element_lines(lines, start, tag):
    '''XML lines from the opening tag at start up to the matching closing tag.'''
    for j in range(start, len(lines)):
        if f"</{tag}>" in lines[j] or (j == start and lines[j].rstrip().endswith("/>")):
            return lines[start:j + 1]
    return lines[start:start + 1]


def github_link(lang, path, line):
    '''Link to the same rule in the LT repository on GitHub (tag v6.6).'''
    relative = path.as_posix().split("/org/languagetool/", 1)[1]
    return f"{GITHUB_BLOB}/{lang}/src/main/resources/org/languagetool/{relative}#L{line}"


def report(tool, lang, text, show_xml):
    matches = check_raw(tool, text)
    print(f"\nZdanie: {text}")
    if not matches:
        print("  LanguageTool nic nie zgłosił.")
        return
    for n, m in enumerate(matches, 1):
        rule = m["rule"]
        offset, length = m["offset"], m["length"]
        rule_id, sub_id = rule["id"], rule.get("subId")
        print(f"\n[{n}] rule_id = {rule_id}" + (f"   sub_id = {sub_id}" if sub_id else ""))
        print(f"    nazwa:      {rule.get('description', '')}")
        print(f"    kategoria:  {rule['category']['id']} ({rule['category'].get('name', '')}), issueType={rule.get('issueType')}")
        print(f"    komunikat:  {m['message']}")
        print(f"    fragment:   {text[:offset]}«{text[offset:offset + length]}»{text[offset + length:]}")
        print(f"    propozycje: {[r['value'] for r in m['replacements'][:5]]}")
        location = find_rule(lang, rule_id, sub_id)
        if location:
            path, line, xml = location
            print(f"    plik:       {path}:{line}")
            print(f"    GitHub:     {github_link(lang, path, line)}")
            if show_xml:
                print("    XML:")
                for xml_line in xml:
                    print("      " + xml_line.rstrip())
            else:
                print(f"    XML:        {xml[0].strip()}")
        else:
            query = urllib.parse.quote(f'repo:languagetool-org/languagetool "{rule_id}"')
            print("    plik:       brak w XML - reguła napisana w Javie")
            print(f"    szukaj:     {GITHUB_SEARCH}{query}")


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Pokazuje regułę LanguageTool dla zdania i jej miejsce w źródłach LT.")
    parser.add_argument("sentences", nargs="*", help="zdania do sprawdzenia (bez nich: tryb interaktywny)")
    parser.add_argument("--lang", choices=["pl", "en"], default="pl")
    parser.add_argument("--raw", action="store_true", help="bez reguł wyłączonych w aplikacji")
    parser.add_argument("--xml", action="store_true", help="wypisz cały XML reguły")
    args = parser.parse_args()

    prepare_environment()
    tool = get_tool(args.lang, args.raw)
    try:
        if args.sentences:
            for sentence in args.sentences:
                report(tool, args.lang, sentence, args.xml)
        else:
            print("Wpisz zdanie (pusta linia kończy):")
            for line in sys.stdin:
                if not line.strip():
                    break
                report(tool, args.lang, line.strip(), args.xml)
    finally:
        if args.raw:
            tool.close()


if __name__ == "__main__":
    main()
