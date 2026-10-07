# UX: three stages, 7 October 2026

## Implemented

1. Access/context: locked course covers and course recommendations open the membership explanation; consultations keep their own introduction for guests; free profile copy acknowledges free courses. Theme expansion arrow survives re-rendering. The first longread title is omitted only when it duplicates the lesson title.
2. Admin workflows: lesson outline is the single lesson navigation list; central module settings remain editable. Course articles open in a dialog using the existing editor, including history and uploads. Material editor has section navigation. Analytics supports search, access filter and whitelisted sorting with parameterized queries. Tracks have version-checked reorder arrows and one-based position input. Track drafts survive reload locally when the server version still matches.
3. Mobile/accessibility: collapsible course outline, mobile analytics rows, keyboard focus, descriptive symbol controls, stronger admin text/button contrast and 44px mobile controls. Saving states use live regions. File selection is not presented as a completed upload.

## Reliability

Autosave now resolves the actual form URL despite an input named `action`, retains newer drafts when an earlier request finishes, and keeps drafts through unsuccessful manual submission. Video-status polling had the same shadowed form-action issue and was repaired. MP4 adaptation rounds dimensions to even values and allows 30 minutes; material editor has explicit retry for failed processing and a re-upload instruction for malformed MP4.

No existing media job was automatically retried and no actual material, subscription, progress, booking or payment was edited for QA. Existing production-only course-navigation assets were imported and preserved rather than overwritten.

## Verification

- Python suite: 71 tests pass, one FFmpeg-dependent local test skipped because FFmpeg is absent locally.
- Dedicated JS test: actual action URL, overlapping autosaves, failed network and manual-submit draft retention.
- Browser fixture: public/member access, secure session, logout, course completion and responsive widths 320/375/430/768/1440; no page JS errors.
- Manual browser checks: mobile lesson outline, embedded article editor, real autosave + reload on isolated test data, mobile material analytics.
- New backend tests: analytics filters/empty result; reorder preserves track steps and rejects stale versions.
- Production verification: website and admin GET routes return 200; existing course-navigation scripts remain available; admin frames use SAMEORIGIN; FFmpeg successfully encodes a synthetic 1280×641 source with the new even-dimension filter.

## Limits / follow-up

Responsive browser checks are not tests on physical iOS/Android devices or Telegram WebViews. Screen-reader behavior and real-device media performance still need hands-on verification. Video encoder repair must be verified with FFmpeg on the server; damaged old MP4 files require a fresh source, and increasing the timeout does not guarantee every long video finishes. Track saving is explicit server saving with a local draft, not server autosave. Article-dialog exit confirms that changes have been saved. This iteration does not add settings to choose analytics columns, change homepage personalization, or redesign the entire admin.
