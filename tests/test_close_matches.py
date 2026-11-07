import pandas as pd

from src.retrieval.region_rank import close_matches


def hits(scores):
    return pd.DataFrame({"doc_id": [f"d{i}" for i in range(len(scores))], "score": scores})


def test_only_hits_near_the_best_score_are_kept():
    assert close_matches(hits([0.0328, 0.0305, 0.0190, 0.0180, 0.0170]))["doc_id"].tolist() == ["d0", "d1"]  # "tambang ilegal kalimantan timur"


def test_a_list_of_close_scores_keeps_all_five():
    assert len(close_matches(hits([0.0328, 0.0316, 0.0314, 0.0310, 0.0282]))) == 5


def test_the_best_hit_always_stays():
    assert close_matches(hits([0.0]))["doc_id"].tolist() == ["d0"]
