# Development Notes

## Recent Changes (January 2026)

### Email Classification System (commit 2febc97)

**Date**: 2026-01-22  
**Branch**: dev  
**Status**: Implemented and deployed

#### What Changed

Restructured email handling to properly classify and separate different email types:

1. **Job Alert/Suggestion Records** (scored)
   - AI-scored against CV using GPT-4o-mini
   - Stored with full parsed job data and scores
   - Included in main "Scored Jobs" report table
   - Auto-deleted after 14 days

2. **Application Confirmation Records** (new)
   - JobServe application confirmations
   - Stored with `job_type: "application"` marker
   - Shown in separate "Job Applications" report table
   - Includes DateTime and Subject
   - Auto-deleted after 28 days
   - Separate from main jobs table (no scores)

3. **Unclassified Email Records** (new)
   - Emails that don't match job alert/suggestion/application patterns
   - Stored with `unclassified: {}` marker (sub-structure)
   - Shown in separate "Unclassified Emails" report table
   - Includes DateTime and Subject
   - No auto-deletion (for reference/debugging)

#### Files Modified

- **newparser_jobserve.py**
  - `classify_job()`: Added logic to classify emails into three types
  - Application handling: Confirmed applications stored with classification flag
  - Unclassified handling: New unclassified records marked with empty sub-structure

- **job_analysis_report.py**
  - `generate_html_table()`: Now filters OUT applications and unclassified emails
  - `generate_applications_table()`: NEW - Shows application confirmations in separate table
  - `generate_unclassified_table()`: NEW - Shows unclassified emails in separate table
  - `create_full_html_document()`: Updated to include all three tables in report
  - `process_job_analysis()`: Enhanced cleanup logic:
    - Jobs older than 14 days: Deleted from DB, UID returned for email deletion
    - Applications older than 28 days: Deleted from DB, UID returned for email deletion

#### Key Features

- **Cleaner Report**: Main jobs table now shows ONLY scored opportunities
- **Application Tracking**: See when you applied for jobs (separate table)
- **Debug Visibility**: Unclassified emails visible for troubleshooting
- **Smart Cleanup**: Automatic deletion of old records with appropriate age thresholds
- **Database Structure**: No separate database files needed - all stored in main `.jobserve.gdbm` with classification markers

#### Testing

Verified with reprocess run on 2026-01-22:
- ✅ 129 total records loaded from database
- ✅ 90 scored jobs correctly identified
- ✅ 2 application confirmations properly classified
- ✅ 37 unclassified emails detected
- ✅ Report generated with three separate tables
- ✅ Old records (37 jobs > 14 days) deleted, UIDs returned for email cleanup

#### Database Schema

New classification in each record:

```
Scored Job: { job_type: "alert|suggestion", scored_job: "...", score: N, ... }
Application: { job_type: "application", parsed_application: {...}, ... }
Unclassified: { unclassified: {}, subject: "...", date: "..." }
```

#### Future Enhancements

1. Application details parsing (job title, date applied, reference)
2. Separate "applied" scoring strategy (different thresholds)
3. Follow-up tracking (when to follow up on applications)
4. Feedback loop (did we get interviews/offers for scored jobs vs others)

---

## Development Workflow Changes

### Git Strategy Update (2026-01-22)

Switched to feature branch development with squash merges:

- **main**: Production stable code only. Safe fallback point.
- **dev**: Main development branch with frequent commits
- **Merge strategy**: Squash commits when merging to main to keep history clean

Benefits:
- Clean production history on main
- Detailed development history on dev
- Easy to revert to last known-good state if needed
- Frequent pushes to dev provide progress visibility

See README.md "Development & Contributing" section for details.

---

## Known Issues

None currently. All three classification types working correctly.

## Next Steps

1. Integrate application parsing to extract more details (when available)
2. Consider different scoring strategy for borderline cases
3. Add application follow-up reminders (check back in N days)
4. Feedback loop: track outcomes vs scores

---

## OCR Pipeline Session (30 Apr 2026)

### Objective

Build a reliable OCR path for RS-encoded Base64 notes shown in the notes browser:

1. render encoded line
2. capture screenshot
3. detect line bounds
4. segment fixed-width glyphs
5. build sample set for OCR matching

### Root Cause and Rendering Fix

- Problem: encoded text was rendered in proportional font (stored as `para`), which broke fixed-stride segmentation.
- Fixes applied:
   - note content changed from `para` to `codeblock` (renders as `<pre><code>`)
   - notes browser font setup changed from `SetStandardFonts(...)` to `SetFonts("", "Courier", [size]*7)` so fixed-width text actually uses Courier
- Notes browser was stopped/restarted via socket API and revalidated with fresh screenshots.

### Verified Courier Geometry

- Working line image: `tmp/rs_note_courier_line_inv_tight.png`
- Width: 1440 px
- Encoded length: 180 chars
- Confirmed pitch: exactly 8 px/char (`180 * 8 = 1440`)

### Vertical Glyph Bounds (Final)

- Initial row-sum method clipped ascenders/tails.
- Final method uses row max brightness and row p99 on the unmarked source line.
- Final accepted bounds:
   - top row: 4
   - bottom row: 17
   - glyph height: 14 px

Validation artifact:

- `tmp/rs_note_courier_line_inv_tight_marked_red_stride8_ybounds_max.png`

### Sample Collection and Coverage Expansion

- First extraction set (`tmp/courier_glyphs`) had 60 unique symbols and missed 4 Base64 chars: `H`, `L`, `n`, `v`.
- Created and loaded a dedicated coverage note with full Base64 alphabet repeated 3 times:
   - key: `john/ocr_glyph_coverage_b64`
- Captured new screenshot and performed stricter dark-text row-band detection + 8 px boundary alignment.
- Merged prior and new extractions into a curated sample corpus:
   - `ocr/glyph_samples/courier10_full`

### Final Coverage Status

- Base64 coverage: 64/64
- Missing symbols: none
- Total samples: 372
- Per-class sample count range: 3 to 17
- Lowest-count classes: `H`, `L`, `n`, `v` (3 each)

Summary report:

- `tmp/glyph_sample_coverage_report_v2.json`

### Important Artifacts Produced

- `tmp/rs_note_courier_screenshot.png`
- `tmp/rs_note_courier_line_inv.png`
- `tmp/rs_note_courier_line_inv_tight.png`
- `tmp/rs_note_courier_line_inv_tight_marked_red_stride8.png`
- `tmp/rs_note_courier_line_inv_tight_marked_red_stride8_ybounds_max.png`
- `tmp/coverage_b64_screenshot.png`
- `tmp/coverage_b64_line_inv_tight_aligned.png`
- `tmp/glyph_sample_coverage_report_v2.json`
- `ocr/glyph_samples/courier10_full/`

### Current Status

- Rendering is now reliably monospace (Courier fixed-width path confirmed).
- Horizontal stride and vertical bounds are established and reproducible.
- Sample library is complete for full Base64 OCR matching.
