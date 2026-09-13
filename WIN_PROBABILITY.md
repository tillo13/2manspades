# Hand-end game-win estimate

The hand-over box now says “You're estimated to win from here ~97% of the time.”
It forecasts the **game outcome after scoring**, including the middle, bag adjustments and
keep-alive rule. It does not grade the last bid or play. The open-hand trick benchmark remains
in historical data and other stats; it is no longer the verdict in this box.

## Model and evidence

`utilities/win_probability_model.json` contains a fitted logistic model and its validation report.
Runtime is a dot product and sigmoid, with no database, external API, or simulation on page
requests. Training uses 7,824 nonterminal positions from 1,261 completed recorded games:
770 human games, 481 Otto games and 10 persona-bot games, through September 13, 2026.
Historical experiment CSVs are excluded: their strategy variants are not reliably identified.
No new rollouts were used for this first estimate.

For feature vector x and fitted coefficients w:

    chance = 1 / (1 + exp(-sum(x[i] * w[i])))

Features, in the artifact's order:

- Intercept, both displayed scores / 100.
- Each score's excess over 200 / 100, floored at zero (proximity to winning).
- Both signed bag counts / 7.
- Marta's numeric strength / 100, plus a linear ramp above strength 60.
- Whether the human leads the next hand.
- Separate intercept adjustments for Otto and persona bots; live human forecasts use neither.

Historical human records generally preserve a rung rather than numeric strength, so these
use preset values 0/30/60/100. New saved forecasts retain numeric strength for future fitting.
Runtime difficulty can be any integer 0–100. Score, bag and strength coefficient directions
are constrained; coefficients are fitted, not hand-picked odds. L2 regularization (coefficient
1; intercept exempt) limits instability. `tools/fit_win_probability.py` uses projected Newton
steps and a backtracking line search.

Validation uses five deterministic folds **grouped by complete game**. All positions of a game
stay together. Each reported prediction came from a model that had not seen that game's outcome.
The shipped coefficients are refitted using all positions after validation. Brier score measures
squared probability error (lower is better); calibration bins separately compare predicted
percentages with actual winning frequency. See the
[scikit-learn calibration reference](https://scikit-learn.org/1.8/modules/calibration.html)
for why both measures matter.

- Human Brier: **0.0803**, versus **0.0910** for the training-fold human win-rate baseline.
- All positions: **0.1429**, versus **0.1656** for source-specific baseline rates.
- Human positions in the 80–100% bin: predicted **92.5%**, observed **92.8%**.
- Recent human subset (35 games since September 7): Brier **0.1226**; the 60–80% bin
  overestimates (71.6% predicted, 53.6% observed, only 14 distinct games).

These are position-weighted metrics. Hands of a game are correlated; position counts must not
be treated as independent samples for confidence intervals. This is an early estimate, not a
claim that every difficulty/score combination is calibrated. The historical human data contains
only 15 Medium, 7 Hard and 10 Ruthless games, versus 738 Easy games.

## Limits and display

The model averages across recorded human players; it is not a personal Luke model. Most human
records are older and predate recent strategy/rule changes. Abandoned games lack outcomes and
are excluded, which can bias the estimate toward people who finish games. Rung-only historical
strength and limited high-level evidence add uncertainty. Retrain as current games accumulate;
inspect recent and per-strength calibration before removing the “Early estimate” label.

Display rounds to whole percentages and prefixes `~`. Unfinished games are limited to 1–99%
to avoid claiming certainty. Completed games, unsupported targets, out-of-range scores/bags,
or a missing model show no estimate. The expandable explanation describes the inputs and the
separate bot baseline. No cards from the next hand or future outcome enter the forecast.

For the screenshot's 271–161 displayed score, one bag each, player led the just-completed hand:
Easy ~97%, Ruthless ~90%. These illustrate the fitted model, not a verified personal probability.

## Refresh

Use the local database proxy and app environment for the read-only export. It exports only
position features, outcomes and game grouping keys; keep this file outside the repository.

    venv_2man/bin/python tools/export_win_positions.py /private/tmp/spades_win_rows.json
    OPENBLAS_NUM_THREADS=1 /usr/local/bin/python3.11 tools/fit_win_probability.py /private/tmp/spades_win_rows.json
    venv_2man/bin/python -m unittest discover -s tests -q

The fitting interpreter needs numpy; the app has no new dependency. Review the exported
validation report and recent-game reliability before releasing refreshed coefficients.
