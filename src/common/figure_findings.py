"""Separate confirmed discrepancies from incomplete model results, including saved reports."""
def figure_details(summary):
    problems, unchecked = [], []
    source = summary.get("problem_details")
    if source is None:
        source = summary.get("details") or []
    unknown = {"nie przeanalizowano", "not analysed", "not analyzed", "częściowo sprawdzono", "partially checked", "częściowo przeanalizowano", "partially analysed"}
    for entry in source:
        text = str(entry).strip()
        status = text.partition(":")[2].partition(" - ")[0].strip().casefold()
        if not text or status in {"poprawny", "correct"}:
            continue
        target = unchecked if status in unknown else problems
        if text not in target:
            target.append(text)
    for entry in summary.get("unchecked_details") or []:
        if entry not in unchecked:
            unchecked.append(entry)
    return problems, unchecked
