from evals.stats import interval, paired_difference


def test_interval_of_a_constant_and_of_a_half():
    assert interval([1] * 88) == (1.0, 1.0)
    lo, hi = interval([1] * 44 + [0] * 44)
    assert lo < 0.5 < hi and 0.35 < lo and hi < 0.65


def test_one_question_out_of_88_is_noise():
    better = [1] * 87 + [0]
    worse = [1] * 86 + [0, 0]
    delta, (lo, hi) = paired_difference(better, worse)
    assert abs(delta - 1 / 88) < 1e-9 and lo <= 0 <= hi


def test_a_consistent_gain_is_not_noise():
    gain, base = [1] * 60 + [0] * 28, [1] * 40 + [0] * 48
    delta, (lo, hi) = paired_difference(gain, base)
    assert lo > 0 and delta > 0.2
    assert paired_difference(base, base) == (0.0, (0.0, 0.0))
