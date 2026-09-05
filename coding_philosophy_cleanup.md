# 2manspades — coding-philosophy retrofit plan

> Written 2026-09-05 at the end of the jukebox day, so the next session can pick this up cold.
> 2manspades predates the philosophy in `~/.claude/rules/*.md` and `~/Desktop/code/HOUSE_STYLE.md`;
> nothing below is a knock on the original build. Everything below is **measured from the tree
> as it sat on 2026-09-05**, with the file and line so it can be re-checked before touching it.
> Andy's order (2026-09-05, "do it, all of it"): safety net first, live risks second, structure
> third, speed fourth, hygiene last. Work paused after step 1 was half done; see "Where it stopped".

---

## 0. Where it stopped (uncommitted on disk, NOT deployed)

Two edits are in the working tree and have not been deployed or committed:

| file | change | why |
|---|---|---|
| `static/jukebox.css` | closed `.ts-sheet` is now `visibility: hidden` and, on desktop, `translateX(100vw)` instead of `translateX(calc(100% + 40px))` | Andy's screenshot showed the closed sheet peeking 25px in from the right edge at ~1300px wide. My own probe had reported the closed sheet at x=1240 on a 1265px viewport and I read past it. `visibility:hidden` also makes a walk `expectHidden` a real assertion instead of a bounding-box guess. |
| `walk.json` | rewritten: 4 viewport profiles, 3 routes, per-step assertions (sheet closed/open, bubble, header bars, bottom bar, difficulty modal, Hoyt stats) | the safety net for every later step. **Has not been run yet.** |

First thing next session: start the app locally (`KUMORI_API_KEY=x venv_2man/bin/python -c "import app as A; A.app.run(port=5077)"`),
run `walk --base http://127.0.0.1:5077` (must pass), then `walk` against prod (must FAIL on the
peeking sheet — that is the canary proving the check can go red), then deploy, then `walk` again (pass).

Live prod as of the last deploy (deploy 15 of the day, threaded gunicorn + login gate) is fine to use; only the peeking sheet is wrong.

---

## 1. The philosophy this is measured against

Sources, in priority order: `~/.claude/rules/00-charter.md` (five non-negotiables), `communication.md`,
`epistemics.md`, `security-infra.md`, `cost-gating.md`, `file-discipline.md`, `skills-use.md`,
`git-deploy.md`; skills `dry-canonical`, `db-speed-first`, `testing-quality`, `flask-kumori-stack`;
and `~/Desktop/code/HOUSE_STYLE.md` (measured fleet defaults, §1 invariants, §2 layout, §4 Python,
§5 frontend, §9 "don't reach for").

The rules that bite here, in one line each:

- **~1000 lines per file, then split; one responsibility per file** (`file-discipline.md`).
- **Iterate, never fork; search before creating; scratch → `_oneoff/`; retired → `_antiquated*/`; never delete** (`file-discipline.md`).
- **DRY by vendoring from `_local_infrastructure/` via `deploy.json → shared_files`; edit the canonical, never the copy** (`dry-canonical`, HOUSE_STYLE §2).
- **Hard canonical routes: DB via postgres_utils pool, secrets from kumori-404602, Anthropic via anthropic_logger, DDL via schema_guard, ship via `deploy`** (`dry-canonical`).
- **Speed is the product: no query in a loop, bound every scan, cache read-mostly endpoints, PROFILE cold+warm before shipping any changed DB call** (`db-speed-first`).
- **Claude tests everything: integration tests for routes/queries, smoke tests, run before deploy, fix edge cases at the source; use `walk`, never a hand-rolled parallel** (`testing-quality`, `skills-use.md`).
- **Frontend: `base.html` + thin templates; custom-property CSS in `static/css`; vanilla JS in `static/js`; no inline style/script; no framework** (HOUSE_STYLE §2, §5).
- **Schema: `SERIAL` ids unless the id leaves the server; `TEXT` not `VARCHAR`; `is_active` not `deleted_at`** (HOUSE_STYLE §9).
- **Python: functions over classes; module docstring on every file; stdlib first** (HOUSE_STYLE §4).
- **Ops: `/health`, `VERSION` stamp, killswitch, visitor_logging, ProxyFix, cron header check are the fleet defaults** (HOUSE_STYLE §1, §6).
- **Security: no hardcoded secrets; no unauthenticated debug surfaces in prod** (`security-infra.md`, HOUSE_STYLE §6).

---

## 2. The violations, with evidence

### 2.1 Over the file-size limit (rule: ~1000)

| file | lines | split along |
|---|---|---|
| `utilities/postgres_utils.py` | 2,124 | `utilities/postgres_utils/` package: `connection.py` (pool, `get_secret`, `db_cursor`), `game_store.py` (hands/games/events/players), `stats.py` (the six stats helpers, 54 queries), `players.py` (leaderboard, difficulty, IP/location) |
| `static/style.css` | 1,703 | `static/css/base.css` (tokens, body, buttons), `game.css` (table, cards, bidding), `header.css` (score bars), `sheet.css` (the table sheet, chat, jukebox — replaces `jukebox.css`), `layout.css` (breakpoints, rail) |
| `static/game.js` | 1,198 | `static/js/game.js` (state polling, play/bid/discard), `chat.js` (Marta: sendMessage/askMarta/typing/badge), `ui.js` (modals, difficulty, login click) |
| `utilities/app_helpers.py` | 1,180 | `session_helpers.py` (init/new game, client_info), `hand_flow.py` (trick/hand/discard processing), keep the rest |
| `static/stats.css` | 1,146 | `static/css/stats.css` trimmed after the shared tokens move to `base.css`; likely lands ~700 |

Why: past ~1000 lines a file stops being readable in one sitting and every edit is a merge hazard. The splits above are along responsibilities that already exist inside the files (the stats helpers are contiguous today, lines ~709–1500 of postgres_utils).

### 2.2 Frontend structure

- **No `templates/base.html`.** Six templates, `{% extends %}` count 0 in all of them; each carries its own `<head>`, meta, GA snippet, fonts. Fix: one `base.html` with `title/head/content/scripts` blocks; every page extends it. Why: one head to edit, one place for the GA snippet and manifest, and the walk's "no broken images / no console errors" applies uniformly.
- **Inline CSS in templates:** `templates/game_detail.html` 247 lines of `<style>`, `templates/player.html` 117 lines. **Inline JS:** `index.html` 32 lines (the `JB_LOGGED_IN` flag plus difficulty/login snippets), `stats.html` 36, `instructions.html` 6, `game_detail.html` 12. Fix: move to `static/css/*.css` and `static/js/*.js`; the one legitimate inline line is the `JB_LOGGED_IN` boolean, which becomes a `data-logged-in` attribute on `<body>`. Why: HOUSE_STYLE §5 — CSS in css/, JS in js/, templates are thin shells.
- **Static layout:** CSS and JS sit loose in `static/` (`style.css`, `stats.css`, `instructions.css`, `jukebox.css`, `game.js`, `jukebox.js`). Fix: `static/css/` and `static/js/`. Why: fleet layout (19/27 apps), and it is where the next person looks.
- **39 inline `onclick=` attributes** across templates (`grep -o "onclick=" templates/*.html | wc -l`). Fix: `data-action` attributes + one delegated `addEventListener` in `ui.js`. Why: inline handlers bind to globals, which is why `toggleChat` had to stay a global today and why `jukebox.js` monkey-patched it.
- **`!important`: 48 in `style.css`, 5 in `jukebox.css`.** Most are the login-banner offsets and my sheet/bubble overrides. Fix: falls out of the CSS rewrite below; target ≤5, each with a comment saying why.
- **Today's jukebox CSS/JS is three iterations layered** (`static/jukebox.css` 163 lines, `static/jukebox.js` 241 lines). Dead or overridden as of 2026-09-05:
  - `.jb-bubble*` rules — the second bubble was removed; the one bubble is `#chatBubbleIcon`.
  - `body.jb-open` / `body.chat-open` rules — nothing sets those classes any more (the sheet sets `body.sheet-open`).
  - the original fixed-position `.jb-panel` rules and the 768–1149 / ≥1150 `.jb-panel` placement rules — overridden by `.ts-sheet .jb-panel`.
  - `.chat-pill`, `.jb-album`, `.jb-mini` each defined twice.
  - `static/style.css` lines ~1640–1675 ("LAYOUT 2026-09-05" block): still positions `.chat-window` as a standalone rail panel; it lives inside the sheet now. Dead, and the sheet CSS has to out-specify it.
  - `jukebox.js`: `openPanel()` wrapper, `isDesktop()`, `panelOpen`, `lastPanel` are leftovers of the two-sheet design; `index.html` still has a hidden `#jbTabNow` "Back" button.
  Fix: rewrite `sheet.css` from the final design (one bubble, one sheet, tabs on narrow, docked on ≥1150) — expected ~90 lines — and prune `jukebox.js` to the sheet/player/pills/beats it actually does. Why: `file-discipline.md` "iterate, never sprawl"; the peeking sheet was a direct symptom of two positioning systems fighting.

### 2.3 DRY and canonical routes

- **Three `get_secret` implementations:** `utilities/google_auth_utils.py:15` (default project twomanspades), `utilities/postgres_utils.py:89` (default kumori-404602), `utilities/gmail_utils.py:37` (`get_secret_version`). Plus `anthropic_logger` has its own (canonical, leave it). Fix: one `get_secret(name, project_id='kumori-404602')` in `utilities/postgres_utils/connection.py`, imported everywhere; the app-specific secrets (`TWOMANSPADES_POSTGRES_*`, Google OAuth) pass `project_id='twomanspades'` explicitly. Why: `dry-canonical` hard route for secrets; three copies means three caches and three places a rename silently misses.
- **Ops hooks missing** (HOUSE_STYLE §1/§6 defaults): no `killswitch`, no `visitor_logging`, no `ProxyFix`, no `X-Appengine-Cron` header check (`grep -c` in app.py = 1 hit total, and `deploy.json` vendors neither). Fix: add `killswitch.py` and `visitor_logging.py` to `deploy.json → shared_files` like the other apps; `ProxyFix` in app.py; cron decorator when the QA robot cron lands.
- **Second deploy path at the root:** `gcloud_deploy.py`, `git_push.sh`. HOUSE_STYLE §2 calls these dead code from the pre-`deploy`-tool era. Fix: move to `_antiquated/`. Why: `git-deploy.md` — raw push bypasses the secret scan and the security scan.
- **Root pollution:** `archive/` (old `app_full.py`, `data.csv`, `gather_pythons.py`, `setup_kumori_db.sh`), `logging/` (game JSON logs written by test-client runs — three from today), `app_structure_map.json`, `map_app.py`, `create_player_views.py`, `skills.md`. Fix: `archive/` → `_antiquated/archive`, `logging/` output redirected to `_oneoff/_test_logs/` when not in production (it already skips the DB when `IS_LOCAL_DEVELOPMENT`; the file write needs the same gate), the one-off scripts → `_oneoff/`. Why: `file-discipline.md` "Andy hates polluted roots".
- **Vendored copies are clean:** `utilities/anthropic_logger.py` and `utilities/schema_guard.py` are byte-identical to `_local_infrastructure/`. Keep it that way; never edit the copies.

### 2.4 Schema and speed

- **`twomanspades.jukebox_plays.play_id UUID PRIMARY KEY`** (`utilities/jukebox.py:88`, added 2026-09-05). HOUSE_STYLE §9 says `SERIAL` unless the id leaves the server. Here the client mints the id and upserts against it across page reloads, so the id does leave the server — defensible, but I did not state it. **Decision for Andy:** keep UUID (my recommendation) or switch to `SERIAL` + a client-generated `client_key TEXT UNIQUE`. Either way, document the choice in the module docstring.
- **Stats page: 54 queries per load**, unmeasured. From `utilities/postgres_utils.py`: `get_overall_game_stats` 14 executes, `get_fun_stats` 12, `get_player_achievements` 11, `get_per_hand_stats` 9, `get_special_card_stats` 5, `get_unified_leaderboard` 3, plus `jukebox_stats` 5. Rule: profile cold and warm with the test client before it ships; I shipped the Hoyt section without timing the page. Fix: time it first (the `db-speed-first` snippet), then collapse the per-helper scans into a handful of `GROUP BY` queries over `hands`/`games`, and put a 60 s TTL cache on the whole payload (it is read-mostly; the jukebox stats endpoint already does this). Target: warm < 100 ms.
- **Game state lives in the Flask session cookie** (`app.py:255,273,371` assign `session['game']`; `trick_history` grows every hand). Two consequences: every request carries a growing cookie, and browsers drop cookies past ~4 KB, which is the leading suspect for the "login resets each visit" report. Fix: store game state server-side keyed by a session id (a `twomanspades.sessions` table or the existing `hands` rows), keep only the id + user in the cookie. Why: `db-speed-first` (payload on every poll) and the login persistence bug. **Verify first**: log `len(request.cookies.get('session',''))` on `/state` for one deploy and read the max — this is the "make the check fail first" rule; do not rebuild on a hunch.
- **No `SELECT 1` problem:** the pool ping exists (`postgres_utils.py:156`). Good.

### 2.5 Security and ops

- **`app.secret_key` is a hardcoded literal** (`app.py:50`). Session signing depends on it; anyone with the repo can forge a login cookie. Fix: `TWOMANSPADES_FLASK_SECRET` in kumori-404602 Secret Manager, loaded at boot, env-var override for local dev. Note: rotating it logs every player out once — ship it the day Andy does the login persistence test.
- **Two unauthenticated debug routes live in prod:** `/debug_async_logging` (`app.py:198`) and `/debug_game_creation` (`app.py:739`). Fix: gate behind the admin check the other apps use, or move to `_oneoff/`. Why: HOUSE_STYLE §6 admin gate; `security-infra.md`.
- **No `/health`, no `VERSION` stamp** (fleet: 19/27). Fix: add both; the deploy tool's post-deploy check can then hit `/health`.
- **Jukebox audio proxy** streams through the app (`utilities/jukebox.py::stream_track`). With threaded gunicorn it no longer blocks plays, but every browser range request is a GCS Class B read (50 k/month free). Not a violation today; note for later: signed URLs would take the app out of the audio path entirely and need `roles/iam.serviceAccountTokenCreator` on the App Engine SA for itself — an IAM change, so it goes through the disclosure block.

### 2.6 Testing

- **No tests directory, no smoke tests, no `test_*.py`.** `walk.json` (before today) covered one route, one viewport, screenshots off.
- Today's verification was ad-hoc playwright scripts in the session scratchpad (`jb_shots.js`, `jb_play.js`, `sheet_test.js`, …). That is the hand-rolled parallel `skills-use.md` forbids, and it let the peeking sheet through because the geometry check printed numbers nobody asserted on.
- Fix: (a) the new `walk.json` (written, unrun — §0); (b) `tests/test_smoke.py` using Flask's test client: one full hand (deal → bid → discard → play 10 tricks → next hand), `/chat_response` with a stubbed router, `/jukebox/event` accept/reject, `/jukebox/audio` 401 vs 206, `/stats` 200, `/health`; (c) `deploy.json → pre_deploy_test` runs `pytest tests/` before the existing anthropic violation check. Why: `testing-quality` — Claude tests, before deploy, and fixtures carry every property the code branches on (the hand fixture must include a blind bid and a nil, since both have their own branches in `computer_logic.py`).

### 2.7 Python style

- **No module docstring:** `app.py`, `utilities/custom_rules.py`, `utilities/gameplay_logic.py`. Fix: one paragraph each — what the file is and how to run/use it.
- Functions over classes holds: 4 classes (`anthropic_logger` ×2, `marta_chat.MartaChat`, `google_auth_utils.SimpleGoogleAuth`, `logging_utils` ×1) vs 229 functions. Nothing to do.
- `app.py` has 31 routes in 780 lines — under the ~80-route split threshold. Leave as one file.

### 2.8 What is already right (do not "fix")

- `deploy "msg"` is the only ship path in practice; both vendored infra files match canonical.
- Secrets come from the kumori hub; DB goes through a `ThreadedConnectionPool` + `RealDictCursor` + `SELECT 1` ping; `/cloudsql` socket on GAE.
- No ORM, no Tailwind/Bootstrap/jQuery, `jsonify` APIs, emoji log tags.
- Marta runs on kumori's free router (cut over 2026-09-05); `anthropic_logger` stays vendored for the pre-deploy check and any future paid call.

---

## 3. The order (Andy-approved 2026-09-05) and what each step proves

| # | step | scope | proof it worked | est. |
|---|---|---|---|---|
| 1 | **Walk** | run `walk.json` local (pass) → prod (must FAIL on peeking sheet) → deploy the sheet fix → prod (pass) | the walk goes red then green on a known defect | 1 h (half done) |
| 2 | **Security** | secret key → Secret Manager; gate/remove the two debug routes; `/health` + `VERSION` | walk still green; `/health` 200; debug routes 403/404; Andy's login survives a browser close | 2 h, one deploy each |
| 3 | **Frontend consolidation** | `base.html`; templates extend; inline CSS/JS out; `static/css` + `static/js`; `onclick` → delegated listeners; rewrite `sheet.css` from the final design; delete the dead rail block; prune `jukebox.js`; `!important` ≤ 5 | walk green after every file; screenshots diffed against the pre-step set; `!important` and `onclick` counts in the commit message | 1–2 d |
| 4 | **File splits** | postgres_utils → package; app_helpers, game.js, style.css split per §2.1 | walk green; `python -c "import app"` clean; smoke tests (step 5) green | 1 d |
| 5 | **Tests** | `tests/test_smoke.py` per §2.6; wired into `deploy.json → pre_deploy_test` | a deliberately broken route fails the deploy (canary), then passes | ½ d |
| 6 | **Speed** | time `/stats` cold/warm; collapse to grouped scans + 60 s cache; measure the session cookie size on `/state` for one deploy; if >3 KB, move game state server-side | numbers before/after in the commit; cookie max logged; login persists | 1 d |
| 7 | **DRY + ops hooks + hygiene** | one `get_secret`; vendor killswitch/visitor_logging; ProxyFix; cron header check; legacy deploy scripts, `archive/`, `logging/`, one-off scripts → `_antiquated`/`_oneoff`; docstrings | walk + smoke green; root `ls` matches HOUSE_STYLE §2 | ½ d |
| 8 | **Decisions for Andy** | UUID play id (recommend keep); QA robot (in-process cron thread playing Marta's brain against her, tagged bot — reuses the step-5 harness) | — | — |

Rules of engagement for every step: one step per deploy (or one file per deploy inside step 3); the walk runs before and after; nothing is deleted, only moved; the commit message carries the measured number that step changed.

---

## 4. Quick reference for the next session

```bash
cd ~/Desktop/code/2manspades
# local server for the walk / tests (no DB from the UK; pages still render)
KUMORI_API_KEY=x venv_2man/bin/python -c "import sys; sys.path.insert(0,'.'); import app as A; A.app.run(port=5077)"
walk --base http://127.0.0.1:5077     # local
walk                                  # prod (walk.json baseUrl)
deploy "msg"                          # only ship path
```

Related memory/state from 2026-09-05: kumori API key row 64 (`TWOMANSPADES_KUMORI_API_KEY`), bucket `twomanspades-hoyt` (private, us-central1, 667 tracks + 43 covers), table `twomanspades.jukebox_plays`, the Hoyt source library is in `~/Downloads/_antiquated/20260905_Hoyt Axton/` pending Andy's decision, kumori router lanes returning `empty` without tripping the breaker is the open kumori-side issue behind Marta's "still looking" retries.

---

## 5. Handoff after the 2026-09-05 implementation pause

Andy asked to stop work because the session had approximately 5% credit remaining. No further implementation or deployment should be started from this session.

### Completed and deployed

- The jukebox/table-sheet CSS fix is deployed. The closed sheet is `visibility: hidden` and the desktop closed transform uses `translateX(100vw)`, eliminating the right-edge peek.
- `walk.json` now covers desktop, laptop, tablet, and mobile profiles; game-sheet open/close, Marta/Hoyt tabs, difficulty modal, instructions, stats, horizontal overflow, broken images, console errors, and 5xx checks.
- The walk was run locally and passed for the home route at all four viewports. Production was run before the fix and correctly failed on the known peeking-sheet defect.
- The hardcoded Flask signing key was replaced with `TWOMANSPADES_FLASK_SECRET` from `kumori-404602` Secret Manager, with an environment override for local development. A random secret version was created; the App Engine service account already had `roles/secretmanager.secretAccessor`.
- `/debug_async_logging` and `/debug_game_creation` now return 404. `/health` returns JSON and the new `VERSION` file reports `2026.09.05.1`.
- `deploy.json` runs the smoke tests and canonical Anthropic check before deploy, then checks `/health` after deploy.
- The first release went through the master wrapper (`~/.local/bin/deploy` → `_local_infrastructure/deploy/deploy.py`), exited 0, and version `version-n1zr0hm3az` serves 100% of traffic. `/health` was verified in production.
- Seven offline regression tests were added in `tests/test_smoke.py`; all pass. They cover a full hand, next hand, nil/blind paths, invalid input, chat retry behavior, jukebox auth/range behavior, debug boundaries, and login persistence across a new game.

### Completed locally but not deployed

- `utilities/postgres_utils.py` was mechanically split into `utilities/postgres_utils/` modules (`connection`, `stats`, `achievements`, `records`, `players`, `game_store`) with a public `__init__.py`. The original file was moved, recoverably, to `_antiquated/20260905_retrofit/utilities/postgres_utils.py`.
- The split imports cleanly and the seven tests still pass, but it has not been committed, deployed, or walked in production.
- The new connection module adds a bounded pool checkout gate, rejects the `postgres` role, supports environment secret overrides, requires loopback DB access for local development, and removes the direct-connection fallback. These changes need review and testing before release; they may need adjustment for the app's current local proxy port and production credentials.
- A read-only stats baseline was started through a loopback Cloud SQL Auth Proxy. It measured 53 application queries plus seven connection pings per `/stats` load; warm helper timings were roughly 1.7–5.8 seconds from this machine. The baseline artifacts are in `_oneoff/stats_baseline_timings.json` and `_oneoff/stats_baseline_payload.json` if present.
- The extra visible launcher used for the first release was moved to `_antiquated/20260905_retrofit/_oneoff/deploy_release.sh`. Continue with the master `deploy "message"` command directly; do not recreate that launcher.

### Continue here next session

1. Inspect `git status --short` and review the uncommitted backend split/connection changes. Run `python -m unittest tests.test_smoke -q` and `python -c "import app"` before touching them.
2. Run the stats baseline to completion through the loopback Auth Proxy, then optimize only after capturing executed query counts and response equivalence. Add a 60-second cache around the complete stats payload if appropriate.
3. Measure the actual `Set-Cookie` size on `/state` and verify that the game cookie contains the opponent hand. Move game state server-side before optimizing further; the cookie-size theory alone was not proven.
4. Walk the split backend locally and in production before deploying it. Use the direct master wrapper and wait for its zero exit status plus version/health verification.
5. Consolidate templates/static assets incrementally after backend behavior is covered. Preserve the current screenshots as the visual baseline. Do not add fleet hooks such as `visitor_logging` or a QA robot without a separate measured reason.
6. Keep the UUID jukebox `play_id`: it is client-generated and crosses the server boundary, which is the documented exception to the SERIAL default.

### Current repository state

The first security release is committed and deployed. The working tree also contains the plan itself, the tests, the `VERSION` file, the current walk/CSS edits, the uncommitted backend split and connection changes, and ignored `_oneoff` scratch artifacts. Nothing was permanently deleted; archived source and the launcher remain recoverable under `_antiquated/20260905_retrofit/`.

---

## 6. 2026-09-05 afternoon session — backend split reviewed and hardened (NOT deployed)

Picked up from §5. Everything below is in the working tree, uncommitted, undeployed.

### Found

- The new `connection.py` checkout gate (`BoundedSemaphore(2)`) was a wedge waiting to happen:
  20 helpers released the pooled conn only on the happy path, `app_helpers._check_and_perform_ip_geolocation`
  called `conn.close()` on a pooled conn (every new game), and the old code only survived this because its
  public-IP direct-connect fallback masked pool exhaustion. With the fallback gone, two leaks = every DB call
  blocks 10 s then raises, per worker, until restart.
- Proven with a canary first: `tests/test_db_release.py` drives all 27 helpers through a fake pool that
  fails after the ping and asserts the gate is back at 2. Against the unfixed tree: 24 failures + 1 error
  (double return raised `ValueError`). After the fix: green.

### Changed

- `connection.py`: `return_db_connection` is idempotent (tracks `id(conn)` of checked-out conns), so a
  `finally` release is safe alongside the existing happy-path releases.
- 22 helpers in `stats.py`, `achievements.py`, `players.py`, `game_store.py`: `conn = None` before the
  `try`, `finally: if conn is not None: return_db_connection(conn)` — the pattern `records.py` already used
  (script that did it: `_oneoff/add_finally_release.py`).
- `app_helpers._check_and_perform_ip_geolocation` and the 404'd debug route in `app.py`: `conn.close()` →
  `return_db_connection(conn)`.

### Verified

- `python -m unittest discover -s tests`: 10 tests, OK (7 smoke + 3 release).
- Real DB through a loopback Auth Proxy on 5433 (`~/cloud-sql-proxy kumori-404602:us-central1:kumori --port 5433`):
  `test_connection` True as role `twomanspades_app`, leaderboard 5 rows, difficulty lookup works, gate at 2 after.
- `walk --base http://127.0.0.1:5077`: `/` and `/instructions` clean at all 4 viewports. `/stats` 200 but
  27.5 s locally (53 queries × UK→us-central1) vs 5.0–5.7 s in prod, so the walk's 30 s navigation timeout
  trips only from here. Not a split regression; it is §2.4's speed item.

### Next

1. `deploy "..."` the split (needs Andy's go). Expect `/health` 200 and `walk` against prod green including `/stats`.
2. Then §5 step 2 (stats speed) and step 3 (cookie size measurement).

---

## 7. 2026-09-05 evening — the plan is done; every step deployed and prod-walked

Superseded: §0 (walk done), §5 "not deployed" items, §6 "Next". Ten deploys today after the split;
each one ran the 12-test suite as the pre-deploy gate and was followed by a `walk` against prod
(16 route/viewport combinations, all clean at the end). Commit messages carry the measured numbers.

| step | shipped as | proof |
|---|---|---|
| 1 walk | walk.json: 4 viewports, 4 routes incl. a full-hand play-through (discard, bid, 10 tricks, next hand) | went red on the peeking sheet, the double bubble handler, the lost mobile banner offset; green after each fix |
| 2 security | (earlier session) secret key, debug routes 404, /health, VERSION | /health 200 = 2026.09.05.2 |
| 3 frontend | base.html + 6 extending templates; static/css + static/js; 0 inline <style>/<script>; 39 onclick → 0 (delegated data-action); sheet.css from the final design; style.css → header/game/layout; !important 53 → 0; jukebox.js pruned | walk screenshots matched the saved baseline (`_oneoff/_walk_baseline/`) |
| 4 splits | postgres_utils package; app_helpers → session_helpers + hand_flow; game.js → chat/game/ui; stats.css → stats + stats_sections | every file ≤ 958 lines; 12 tests OK |
| 5 tests | tests/test_smoke (7), test_db_release (3), test_stats_cache (2), wired in deploy.json | gate blocked one deploy (segfault at exit from the visitor flusher) and was fixed at the source |
| 6 speed | /stats 60 s single-flight cache: warm 5.0 s → 2 ms server-side; cookie measured 1.6 KB max, game state stays in the cookie | numbers in commit cf967b1 |
| 7 DRY/ops/hygiene | one get_secret; visitor_logging vendored (rows landing in kumori_ops.visitor_log); ProxyFix; logs → _oneoff/_test_logs; legacy scripts, archive/, one-offs moved to _antiquated/_oneoff; docstrings | root `ls` = app.py app.yaml CLAUDE.md deploy.json README.md requirements.txt skills.md VERSION walk.json + this file |
| 8 decisions | UUID play_id kept and documented in utilities/jukebox.py | — |

Not done, on purpose: killswitch (guards paid-API spend; this app has no paid calls, so it would be dead
code) and the cron header check (no cron route exists). QA robot: Andy's call, not started.

Also today, outside the plan: login from the Hoyt tab returns to an open Hoyt tab with the music
started. Marta's song-question failures are the kumori router's high tier (one working lane, one
25 s hanger, 13 gated); brief handed to the kumori session, nothing changed app-side.

Where things live now: original style.css/jukebox.css/app_helpers.py/postgres_utils.py under
`_antiquated/20260905_retrofit/`; dead CSS in `dead_css_2026-09-05.css` there; one-off scripts and
walk baseline under `_oneoff/`. Local walk recipe: `venv_2man/bin/python _oneoff/run_local.py 5077`
(skips the visitor-telemetry thread) with the Auth Proxy on 5433, then `walk --base http://127.0.0.1:5077`.
