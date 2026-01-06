# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `skills.md` first** - contains coding style preferences (minimal code, no bloat, no placeholders).

## Project Overview

Two-Man Spades is a web-based card game where a human player (Tom) plays against an AI opponent (Marta). It's a Flask application deployed to Google App Engine with a vanilla JavaScript frontend.

## Development Commands

```bash
# Deploy to Google App Engine (production)
python gcloud_deploy.py

# Activate virtual environment
source venv_2man/bin/activate
```

## Architecture

### Backend (Python/Flask)

**Main entry point:** `app.py` - Flask routes, uses `utilities/app_helpers.py` for logic

**Core game logic in `utilities/`:**
- `app_helpers.py` - Refactored helper functions (game state, trick resolution, etc.)
- `gameplay_logic.py` - Deck creation, hand initialization, card validation, trick resolution
- `computer_logic.py` - AI decision-making for bidding, discarding, and play strategy (tunable difficulty parameters at top)
- `custom_rules.py` - Special scoring rules: parity system, bags, blind bidding, special cards (7♦, 10♣)
- `claude_utils.py` - Claude API integration for Marta's chat responses
- `logging_utils.py` - Game logging and async DB operations
- `postgres_utils.py` - Database queries for stats/leaderboards
- `gmail_utils.py` - Error notification emails
- `google_auth_utils.py` - Google OAuth for login

**Key game state stored in Flask session:**
- Phase flow: `blind_decision` → `discard` → `bidding` → `playing`
- Scores use display score (base + bags in ones column) vs base score internally

### Frontend

- `static/game.js` - Game state polling, card interactions, UI updates
- `static/style.css` - Responsive design
- `templates/index.html` - Main game template

### Deployment

- `app.yaml` - Google App Engine config (Python 3.12, gunicorn)
- Production URL: https://2manspades.com (twomanspades.appspot.com)
- Uses Google Secret Manager for ANTHROPIC_API_KEY

## Game Rules Summary

- 11 cards dealt, 1 discarded, 10 tricks played
- Parity system (even/odd) determines discard pile winner and first leader
- Bags: overtricks accumulate, 7 bags = -100 points, -5 bags = +100 bonus
- Special cards: 7♦ removes 2 bags, 10♣ removes 1 bag from trick/discard winner
- Blind bidding: available when 100+ points behind, doubles points/penalties
- Win condition: 300 points or 300+ point lead (mercy rule)

## AI Tuning

Computer strategy parameters in `utilities/computer_logic.py`:
```python
MAX_REASONABLE_BID = 6          # Cap on Marta's bids
BAG_AVOIDANCE_STRENGTH = 0.92   # How aggressively to avoid bags
NIL_STRICTNESS = 0.8            # Threshold for nil attempts
```
