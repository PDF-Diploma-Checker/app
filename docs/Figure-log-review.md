# Figure log review

Source: `diploma_checker_logi_68c1abb6.zip`, final analysis on 14 November 2026.
The archive contains logs and system metadata, not the thesis PDF or its figures.
This review establishes code and reporting defects, not full-document accuracy.

| Logged result | Assessment |
| --- | --- |
| 28 figures, 3 with problems, 25 correct | The 25 positive verdicts are not all supported: the checker explicitly skipped comparisons when read values could not be verified, then returned `True`. |
| Figure 7.7: text `37/80`, image `35` | A ratio cannot be compared as a single count without interpreting its denominator and unit. The existing numeric parser did not establish comparable quantities. |
| Figure 6.17: text `0,81`, image `0` | Neither the corresponding figure label nor the source evidence is retained in this verdict. The logs alone cannot establish whether this is a true discrepancy or an unrelated axis/series value. |
| Figure 6.16: no genuine reference | Unresolved without the PDF; the archive does not establish that the reference is absent. |
| Repeated entries for a single figure | The raw report is per reference paragraph. Totals already count unique figures, but a later successful comparison could overwrite an incomplete one in the summary. |

The fix distinguishes unverified comparisons from confirmed agreement. A mismatch
must provide literal excerpts from both input sources, each containing its claimed
value. The figure value must therefore occur in the reading, rather than only in
a separate numeric list. Ratios are left unassessed instead of compared as counts.
An incomplete comparison remains visible when another paragraph is correct.

This does not prove that a vision-model reading matches the original pixels or
that two literal excerpts describe the same experimental condition. The prompt
requires the same item, series and unit, but model reasoning remains fallible.
No real-model or GPU rerun was performed for this change. Regression tests use
controlled answers and cover genuine mismatches as well as unsupported evidence.
