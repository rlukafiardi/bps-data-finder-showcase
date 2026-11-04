"""Bootstrap intervals over per-question scores: the 88 questions are a small sample, so a difference of a
question or two is noise. Questions are resampled with replacement; paired comparisons use the same resamples."""

import numpy as np

RESAMPLES = 2000
SEED = 0


def _resamples(n):
    return np.random.default_rng(SEED).integers(0, n, size=(RESAMPLES, n))


def interval(scores):
    """95% percentile interval of the mean of a per-question score (0/1 hit or reciprocal rank)."""
    means = np.asarray(scores, dtype=float)[_resamples(len(scores))].mean(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def paired_difference(scores_a, scores_b):
    """(mean of a - b, 95% interval) on the same resampled questions; an interval holding 0 means noise."""
    diff = np.asarray(scores_a, dtype=float) - np.asarray(scores_b, dtype=float)
    means = diff[_resamples(len(diff))].mean(axis=1)
    return diff.mean(), tuple(np.percentile(means, [2.5, 97.5]))
