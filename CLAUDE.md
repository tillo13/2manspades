# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `skills.md` first** - contains coding style preferences (minimal code, no bloat, no placeholders).

## Project Overview

Two-Man Spades is a web-based card game where a human player plays against an AI opponent (Marta). Flask application deployed to Google App Engine with vanilla JavaScript frontend.

## Deployment

```bash
# ALWAYS use the centralized deploy tool (git push + GCP deploy in one command)
deploy "commit message"
```
- NEVER use raw `git push`, `gcloud app deploy`, or old `git_push.sh`/`git_push.bat` scripts
- `deploy` always does BOTH git push and GCP deploy — that is the default and expected behavior
- See `~/.claude/skills/deploy-to-gcp.md` for flags like `--git-only` or `--gcp-only` (only if explicitly needed)
- Config: `deploy.json` in project root | Tool: `~/Desktop/code/master_gcp_deploy/deploy.py`

## Development Commands

```bash
# Activate virtual environment
source venv_2man/bin/activate

# Run database queries (requires venv)
python3 -c "from utilities.postgres_utils import get_db_connection; ..."
```

## Architecture

### Backend (Python/Flask)

**Main entry point:** `app.py` - Flask routes, uses `utilities/app_helpers.py` for logic

**Core game logic in `utilities/`:**
- `app_helpers.py` - Game initialization, phase processing, trick resolution
- `gameplay_logic.py` - Deck creation, hand initialization, card validation
- `computer_logic.py` - AI bidding/playing with difficulty system (`get_difficulty_params()`)
- `custom_rules.py` - Parity system, bags, blind bidding, special cards (7♦, 10♣)
- `postgres_utils.py` - All database queries for stats/leaderboards/player profiles
- `logging_utils.py` - Game event logging with async DB operations
- `google_auth_utils.py` - Google OAuth for login

**Key game state stored in Flask session:**
- Phase flow: `blind_decision` → `discard` → `bidding` → `playing`
- `session['difficulty']` - AI difficulty (easy/medium/ruthless), persists across games
- `session['user']` - Google auth info if logged in

### Frontend

- `static/game.js` - Game state polling, card interactions, difficulty modal
- `static/style.css` - Responsive design
- `templates/index.html` - Main game template
- `templates/stats.html` - Leaderboards and player achievements
- `templates/player.html` - Individual player game history
- `templates/game_detail.html` - Detailed breakdown of a specific game

### Database

PostgreSQL on Google Cloud. Key tables:
- `hands` - Each game session (includes `difficulty` column)
- `game_events` - All game actions with timestamps
- `players` - Player profiles with Google auth and preferences

Key views (in `twomanspades` schema):
- `vw_player_game_details` - Completed games with player identity
- `vw_player_identity` - Maps hand_id to player name (Tom/Luke/Jon/Andy)
- `vw_unified_leaderboard` - Aggregated player stats

### Infrastructure

- `app.yaml` - Google App Engine config (Python 3.12, gunicorn)
- Production URL: https://2manspades.com
- Uses Google Secret Manager for ANTHROPIC_API_KEY

## Game Rules Summary

- 11 cards dealt, 1 discarded, 10 tricks played
- Parity system (even/odd) determines discard pile winner and first leader
- Bags: overtricks accumulate, 7 bags = -100 points, -5 bags = +100 bonus
- Special cards: 7♦ removes 2 bags, 10♣ removes 1 bag from trick/discard winner
- Blind bidding: available when 100+ points behind, doubles points/penalties
- Win condition: 300 points or 300+ point lead (mercy rule)

## AI Difficulty System

Difficulty stored in session and user profile. Parameters in `computer_logic.py`:
```python
def get_difficulty_params(difficulty='easy'):
    # easy: bid_boost=0.3, bag_avoid=0.92, max_bid=6
    # medium: bid_boost=0.5, bag_avoid=0.95, max_bid=7
    # ruthless: bid_boost=0.7, bag_avoid=0.98, max_bid=8
```
