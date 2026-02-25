# TODO 

1. DONE — fetch_emails.py > resulting meta.json sender spacing fixed.

2. DONE — process_meeting.py > stdout no longer includes Telemost default frontmatter.

3. DONE — summary preview reduced from 500 to 250 chars.
   - `summary_preview` now uses `[:250]`.

4. DONE — minimal output by default; detailed output only with `--verbose`.
   - `report_result(..., verbose=False)` prints compact single-line status.
   - Detailed multi-line report shown only with `--verbose`.

5. DONE — process_meeting.py > meeting.meta.json root `date` removed.
   - `meta` no longer writes `"date"`.

6. DONE — `telemost_summary` preserved in meeting metadata.
   - Added `telemost_summary` propagation in merge stage and output `meeting.meta.json`.

7. DONE — summary generation now copies original `email_body.txt` when available.
   - Added `summary_file` tracking in merge stage.
   - `process_meeting()` copies source file to `summary.txt` via `shutil.copyfile(...)`.
   - Falls back to text write only when source file is unavailable.

8. process_meeting.py: ref_utc comes from `transcipt.txt` and then used to make dir name. Consequence: no dir name for recordings. Change the logic to parse date from `email_body.txt` (either `Запись началась 13.02.2026 в 19:08` or `Конспектирование началось 13.02.2026 в 19:08 (MSK)` both contain `13.02.2026 в 19:08`)

9. process_meeting.py: parse TELEMOST_UID_RE from `email_body.txt` NOT HTML! 

10. HTML should not be used for anything! Remove HTML processing altogether and switch all processing to plain-text `email_body.txt`