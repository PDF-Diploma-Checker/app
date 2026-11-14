# Language log review

Scope: `app.log` (25,013 lines) and archived `crash.log` from
`diploma_checker_logi_68c1abb6.zip`; baseline `upstream/staging` at `ab1bf9c`.
Extracted app log matches the archive (SHA-256
`eee949b3b409c2e9c2723e634b82f898a95bc0870974d70e72c14b2735c795f9`).
Line references below address that original app log, not this report.
No PDF was supplied or inspected. Examples contain tokens only.

## Aggregate evidence

Counts are log events across repeated runs/documents, **not unique errors** or an
accuracy estimate. `REPORTED` precedes model review and is not the final result.

| Decision | Events |
|---|---:|
| Reported | 394 |
| Dropped by deterministic filters | 3,918 |
| Model rejected | 183 |
| Model confirmed | 59 |
| Model not asked | 152 |

Reported categories include 149 TYPOS, 119 PUNCTUATION, 26 NO_SUBJECT,
24 ACRONYM_UNDEFINED and 20 DECIMAL. All 20 DECIMAL events were subsequently
model-rejected. There are 147 reported `MORFOLOGIK_RULE_EN_GB` events, all labelled
Polish blocks; 108 model rejections, 3 confirmations and 36 not-asked events carry
that rule. These totals do not establish that all 147 are false positives.

## Findings and changes

- **Decimal false negatives:** lines 17511–17514 / 20672–20675 and
  21818–21821 / 24979–24982 show `0.6`, `0.5`, `1.6`, `1.3` reported and then
  rejected. The model treats a dot as acceptable in technical Polish prose.
  Existing policy explicitly checks dot decimals in Polish and comma decimals
  in English; it already excludes math/code, references, versions and quotes.
  DECIMAL is now protected from model rejection, like PERSONAL_FORM. Separator
  detection, confidence labels and exceptions are unchanged.
- **Decimal false-positive candidates:** lines 5106–5114 include `5.0` in an
  industry designation and `2.13`, `4.3` in apparent equation references. Those
  earlier-run events are not evidence that every model rejection was wrong.
  Without PDF structure/chapter metadata they cannot be replayed faithfully;
  no blanket reference-word or decimal-policy change was made.
- **English spelling contamination:** lines 1255–1258 report Polish tokens
  `przyjmując`, `amplitudy`, `Całkowity`, `błąd` with the English rule; the last
  receives English suggestions. Code inspection identifies two paths: replacing
  original Polish spelling findings with an English cross-check, and extracting
  word errors from sentence-wide SYNTAX findings using the opposite language.
  The cross-check now only accepts intentional foreign words or retains the
  original diagnosis, span and suggestions. SYNTAX recovery now obtains spelling
  findings from the primary language per word, with the foreign-language veto
  retained. This prevents the English dictionary from inventing Polish spelling
  errors in a sentence-wide finding; it does not eliminate dictionary gaps.
- **Other false positives / limits:** `robotycznych` (21795/24961) and technical
  vocabulary such as `serwonapędów` are rejected by the model. Vocabulary gaps
  may remain after the provenance fix; no document-specific whitelist was added.
- **Unresolved false-negative candidates:** `zaadaptoW` is dropped as a proper
  name (1035); `platformieANYmal` is model-rejected as a name (21804/24970), and
  `mentacją` is called a technical term (21799/24965). These may involve extraction
  joins or split words. The PDF is needed to distinguish source errors from
  extraction artifacts; no guessed correction or global name-filter change.
  Conversely `porpzednim` is retained without model review (21811/24707), showing
  the existing one-letter typo protection works for that example.

## Crash

The archive contains one fatal segmentation-fault dump. Its current thread ends
at `app/main.py:129` (Qt event loop); the other thread is in
`resource_monitor.py:122`, `Event.wait`. Waiting is normal sampler behavior and
is not evidence that the resource monitor caused the fault. The dump has no
native stack or offending extension identification. No concrete lifecycle fault
was established from the trace and inspected code; no speculative crash fix.

Lines 20686–20689 record analysis completion and PDF loading at 16:28:14–15;
20690–20692 show restart at 16:28:40 and cleanup of leftover LanguageTool servers.
The archive timestamps the crash file at 16:28, but the dump itself has no event
timestamp. This bounds correlation, not causation. All 150 app-log ERROR events
are from `llama.cpp`; severity alone does not tie those diagnostics to this crash.
A native backtrace/core dump plus reproduction steps are needed to attribute it.

## Validation

101 focused unittest cases passed, no skips, using the existing CPU environment
with `CUDA_VISIBLE_DEVICES=''`. Modules: `unit_tests.llm.test_linguistic_review`,
`unit_tests.linguistics.typos.test_bilingual_findings`,
`unit_tests.linguistics.typos.test_sentence_wide_match`,
`unit_tests.linguistics.typos.test_typo_check`,
`unit_tests.linguistics.decimal_point.test_decimal_point_extractor`.
New coverage checks protected PL/EN decimal findings without model creation,
primary rule/suggestions/offset preservation, foreign-word acceptance, and
sentence-wide recovery without English-generated Polish errors. LanguageTool
and model calls in routing tests are mocked; no live model, GPU, packaged-app
crash reproduction or full-document accuracy measurement. No image changes or
`build_linux.sh` changes; image PR #140 is separate.
