# Website color refresh — 7 October 2026

- Default web theme is light, independently of the operating system: ivory canvas, near-white cards, dark warm text and restrained terracotta accents.
- Local cream/peach gradients highlight the welcome and introductory sections, not reading content or the whole page.
- Header has an accessible 44px theme switch. An explicit dark theme uses charcoal/warm-neutral surfaces. Preference persists in localStorage, is applied before first paint and synchronizes across tabs. Unavailable storage falls back safely to light.
- Palette changes are limited to website assets and the website HTML wrapper. Telegram Mini App, admin, data and subscriptions remain unchanged.

Verification: nine website backend tests; existing guest/member UI flow; explicit theme/default/persistence/keyboard tests across fifty responsive views (320–1440px); 28 axe checks across seven guest pages, two themes and two widths, no detected violations on the fixture. This is automated coverage, not a claim of full WCAG conformance or real-phone verification.

Deployment guards existing file hashes and backs up all three production files before replacement; only the web/admin service restarts. Prior production navigation enhancements are preserved.
