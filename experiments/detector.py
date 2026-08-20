# The four early-warning models of docs/overview.md, trained and scored the
# same way so the only thing that differs between them is what they get to see.
#
# Model 1 gets the situation. Model 2 adds the observable firm record, model 3
# adds the traders' private chat, and model 4 adds private reasoning. The
# question the paper asks is whether 4 beats 3: does the scratchpad carry
# information about what the trader is about to do, beyond the pressure it is
# visibly under and everything it has already said?
#
# Three choices here are load-bearing.
#
# Grouping by episode. Rounds inside an episode share a trader's running state
# and its accumulated history, so a row from round 8 is not independent of the
# row from round 7. Splitting rows at random would put both sides of that pair
# on either side of the split and inflate every score. Every split in this file
# is grouped by episode_id.
#
# Out-of-fold pooling instead of one held-out test set. Misconduct is rare, and
# a single test split of a 60-episode sweep can easily land with a handful of
# positives, where AUPRC is mostly noise. Cross-validating and pooling the
# out-of-fold scores uses every row exactly once as a test row.
#
# A paired bootstrap over episodes for model 3 against model 4. The two models
# score the same rows, so their errors are correlated, and comparing two
# independent confidence intervals would understate the evidence. Resampling
# episodes and taking the difference within each resample keeps the pairing.

from dataclasses import dataclass, field
import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from typing import Optional, Sequence

from experiments.dataset import Row, label_of


# Nested exactly as the overview specifies: each model sees everything the
# previous one saw, plus one new source.
MODELS = {
    "1_situation": ("situation",),
    "2_observable": ("situation", "observable"),
    "3_private_chat": ("situation", "observable", "private_chat"),
    "4_private_reasoning": (
        "situation",
        "observable",
        "private_chat",
        "reasoning",
    ),
}

TEXT_BLOCKS = {"observable", "private_chat", "reasoning"}
INSPECTION_BUDGETS = (0.05, 0.10, 0.20)


@dataclass
class Evaluation:
    model: str
    rows: int
    positives: int
    base_rate: float
    auprc: float
    auprc_lift: float
    auroc: float
    brier: float
    recall_at_budget: dict[str, float] = field(default_factory=dict)
    calibration: list[dict[str, float]] = field(default_factory=list)
    scores: Optional[np.ndarray] = None
    labels: Optional[np.ndarray] = None
    groups: Optional[np.ndarray] = None


def _numeric_matrix(
    rows: Sequence[Row], blocks: Sequence[str]
) -> tuple[np.ndarray, list[str]]:
    names: list[str] = []
    for block in blocks:
        names.extend(f"{block}.{key}" for key in sorted(getattr(rows[0], block)))
    matrix = np.zeros((len(rows), len(names)), dtype=float)
    for index, row in enumerate(rows):
        position = 0
        for block in blocks:
            values = getattr(row, block)
            for key in sorted(values):
                matrix[index, position] = values[key]
                position += 1
    return matrix, names


def _text_of(rows: Sequence[Row], block: str) -> list[str]:
    return [getattr(row, f"{block}_text") for row in rows]


def _fit_transform(
    train_rows: Sequence[Row],
    test_rows: Sequence[Row],
    blocks: Sequence[str],
) -> tuple[sparse.csr_matrix, sparse.csr_matrix]:
    # Every vectorizer and scaler is fitted on the training rows only. A TF-IDF
    # vocabulary built over the whole dataset would let a fold's test rows
    # influence their own features, which is the quiet kind of leakage that
    # survives a grouped split.
    train_numeric, _ = _numeric_matrix(train_rows, blocks)
    test_numeric, _ = _numeric_matrix(test_rows, blocks)
    scaler = StandardScaler().fit(train_numeric)
    train_parts = [sparse.csr_matrix(scaler.transform(train_numeric))]
    test_parts = [sparse.csr_matrix(scaler.transform(test_numeric))]

    for block in blocks:
        if block not in TEXT_BLOCKS:
            continue
        train_text = _text_of(train_rows, block)
        if not any(text.strip() for text in train_text):
            continue
        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            min_df=3,
            max_features=3000,
            sublinear_tf=True,
            strip_accents="unicode",
        )
        try:
            train_parts.append(vectorizer.fit_transform(train_text))
        except ValueError:
            # Every term fell below min_df; the block carries no usable text
            # in this fold. Better to drop it than to relax min_df only here
            # and change the feature space fold to fold.
            continue
        test_parts.append(vectorizer.transform(_text_of(test_rows, block)))

    return sparse.hstack(train_parts).tocsr(), sparse.hstack(test_parts).tocsr()


def _new_model(seed: int) -> LogisticRegression:
    # L2-regularized logistic regression, identical for every model and every
    # input block, as the overview requires. class_weight balances the rare
    # positive class so the fit is not dominated by the majority.
    return LogisticRegression(
        penalty="l2",
        C=0.5,
        solver="liblinear",
        class_weight="balanced",
        max_iter=5000,
        random_state=seed,
    )


def _recall_at_budget(
    labels: np.ndarray, scores: np.ndarray, budget: float
) -> float:
    positives = int(labels.sum())
    if positives == 0:
        return float("nan")
    count = max(1, int(round(budget * len(labels))))
    order = np.argsort(-scores, kind="stable")[:count]
    return float(labels[order].sum() / positives)


def _calibration_table(
    labels: np.ndarray, scores: np.ndarray, bins: int = 5
) -> list[dict[str, float]]:
    edges = np.quantile(scores, np.linspace(0, 1, bins + 1))
    edges[0] -= 1e-12
    table = []
    for index in range(bins):
        low, high = edges[index], edges[index + 1]
        if high <= low:
            continue
        mask = (scores > low) & (scores <= high)
        if not mask.any():
            continue
        table.append(
            {
                "bin": index + 1,
                "count": int(mask.sum()),
                "mean_predicted": float(scores[mask].mean()),
                "observed_rate": float(labels[mask].mean()),
            }
        )
    return table


def _score(model_name: str, labels: np.ndarray, scores: np.ndarray,
           groups: np.ndarray) -> Evaluation:
    positives = int(labels.sum())
    base_rate = float(labels.mean()) if len(labels) else 0.0
    if positives == 0 or positives == len(labels):
        return Evaluation(
            model=model_name,
            rows=len(labels),
            positives=positives,
            base_rate=base_rate,
            auprc=float("nan"),
            auprc_lift=float("nan"),
            auroc=float("nan"),
            brier=float("nan"),
            scores=scores,
            labels=labels,
            groups=groups,
        )
    auprc = float(average_precision_score(labels, scores))
    return Evaluation(
        model=model_name,
        rows=len(labels),
        positives=positives,
        base_rate=base_rate,
        auprc=auprc,
        # AUPRC is not comparable across targets with different base rates, so
        # every table also carries the ratio to the always-positive baseline.
        auprc_lift=auprc / base_rate if base_rate else float("nan"),
        auroc=float(roc_auc_score(labels, scores)),
        brier=float(brier_score_loss(labels, scores)),
        recall_at_budget={
            f"{int(budget * 100)}%": _recall_at_budget(labels, scores, budget)
            for budget in INSPECTION_BUDGETS
        },
        calibration=_calibration_table(labels, scores),
        scores=scores,
        labels=labels,
        groups=groups,
    )


def cross_validated(
    rows: Sequence[Row],
    target: str,
    costly_only: bool = False,
    folds: int = 5,
    seed: int = 0,
) -> dict[str, Evaluation]:
    labels = np.array(
        [label_of(row, target, costly_only) for row in rows], dtype=int
    )
    groups = np.array([row.episode_id for row in rows])
    unique_groups = np.unique(groups)
    folds = min(folds, len(unique_groups))
    if labels.sum() < 2 or folds < 2:
        return {
            name: _score(name, labels, np.full(len(labels), labels.mean()), groups)
            for name in MODELS
        }

    splitter = GroupKFold(n_splits=folds)
    results: dict[str, Evaluation] = {}
    for name, blocks in MODELS.items():
        out_of_fold = np.zeros(len(rows), dtype=float)
        for train_index, test_index in splitter.split(
            np.zeros(len(rows)), labels, groups
        ):
            train_rows = [rows[i] for i in train_index]
            test_rows = [rows[i] for i in test_index]
            train_labels = labels[train_index]
            if train_labels.sum() == 0 or train_labels.sum() == len(train_labels):
                # A fold with one class cannot fit. Predicting the training
                # base rate keeps every row scored exactly once without
                # inventing a ranking the model never learned.
                out_of_fold[test_index] = train_labels.mean()
                continue
            train_matrix, test_matrix = _fit_transform(
                train_rows, test_rows, blocks
            )
            model = _new_model(seed)
            model.fit(train_matrix, train_labels)
            out_of_fold[test_index] = model.predict_proba(test_matrix)[:, 1]
        results[name] = _score(name, labels, out_of_fold, groups)
    return results


def leave_one_pressure_out(
    rows: Sequence[Row],
    target: str,
    costly_only: bool = False,
    seed: int = 0,
) -> dict[int, dict[str, Evaluation]]:
    # The generalization test the overview asks for: train on four pressure
    # levels and score the fifth, which the model has never seen. Held-out rows
    # come from a distribution the training set does not contain, so this is
    # the only number here that speaks to transfer rather than interpolation.
    labels = np.array(
        [label_of(row, target, costly_only) for row in rows], dtype=int
    )
    pressures = np.array([row.pressure_level for row in rows])
    groups = np.array([row.episode_id for row in rows])
    results: dict[int, dict[str, Evaluation]] = {}

    for held_out in sorted(set(pressures.tolist())):
        test_mask = pressures == held_out
        train_mask = ~test_mask
        train_labels = labels[train_mask]
        test_labels = labels[test_mask]
        if train_labels.sum() == 0 or test_labels.sum() == 0:
            continue
        train_rows = [row for row, keep in zip(rows, train_mask) if keep]
        test_rows = [row for row, keep in zip(rows, test_mask) if keep]

        per_model: dict[str, Evaluation] = {}
        for name, blocks in MODELS.items():
            train_matrix, test_matrix = _fit_transform(
                train_rows, test_rows, blocks
            )
            model = _new_model(seed)
            model.fit(train_matrix, train_labels)
            scores = model.predict_proba(test_matrix)[:, 1]
            per_model[name] = _score(
                name, test_labels, scores, groups[test_mask]
            )
        results[held_out] = per_model
    return results


def paired_bootstrap(
    first: Evaluation,
    second: Evaluation,
    draws: int = 2000,
    seed: int = 0,
) -> dict[str, float]:
    # Resamples episodes, not rows. An episode is the independent unit here,
    # so resampling rows would treat ten correlated rounds as ten separate
    # observations and produce an interval that is far too tight.
    if first.scores is None or second.scores is None:
        return {}
    labels = first.labels
    groups = first.groups
    unique_groups = np.unique(groups)
    index_by_group = {name: np.flatnonzero(groups == name) for name in unique_groups}
    generator = np.random.default_rng(seed)

    deltas = []
    for _ in range(draws):
        chosen = generator.choice(unique_groups, size=len(unique_groups), replace=True)
        index = np.concatenate([index_by_group[name] for name in chosen])
        sample_labels = labels[index]
        if sample_labels.sum() == 0 or sample_labels.sum() == len(sample_labels):
            continue
        deltas.append(
            average_precision_score(sample_labels, second.scores[index])
            - average_precision_score(sample_labels, first.scores[index])
        )
    if not deltas:
        return {}
    deltas = np.array(deltas)
    return {
        "delta_auprc": float(second.auprc - first.auprc),
        "ci_low": float(np.quantile(deltas, 0.025)),
        "ci_high": float(np.quantile(deltas, 0.975)),
        # Share of resamples where the richer model did no better. A one-sided
        # bootstrap p-value for "model 4 adds nothing".
        "p_no_gain": float((deltas <= 0).mean()),
        "draws": int(len(deltas)),
    }


def top_features(
    rows: Sequence[Row],
    target: str,
    model_name: str,
    costly_only: bool = False,
    count: int = 12,
    seed: int = 0,
) -> list[tuple[str, float]]:
    # Fitted on everything, for description only. These weights are read as
    # "what the detector keys on", never as an out-of-sample result.
    blocks = MODELS[model_name]
    labels = np.array(
        [label_of(row, target, costly_only) for row in rows], dtype=int
    )
    if labels.sum() == 0 or labels.sum() == len(labels):
        return []

    numeric, names = _numeric_matrix(rows, blocks)
    scaler = StandardScaler().fit(numeric)
    parts = [sparse.csr_matrix(scaler.transform(numeric))]
    feature_names = list(names)
    for block in blocks:
        if block not in TEXT_BLOCKS:
            continue
        text = _text_of(rows, block)
        if not any(item.strip() for item in text):
            continue
        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            min_df=3,
            max_features=3000,
            sublinear_tf=True,
            strip_accents="unicode",
        )
        try:
            parts.append(vectorizer.fit_transform(text))
        except ValueError:
            continue
        feature_names.extend(
            f"{block}.text:{term}" for term in vectorizer.get_feature_names_out()
        )

    matrix = sparse.hstack(parts).tocsr()
    model = _new_model(seed)
    model.fit(matrix, labels)
    weights = model.coef_[0]
    order = np.argsort(-np.abs(weights))[:count]
    return [(feature_names[i], float(weights[i])) for i in order]
