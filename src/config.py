EMBED_MODEL = "intfloat/multilingual-e5-small"  # e5 expects "query: " / "passage: " prefixes
REWRITE_MODEL = "gemini-3.5-flash-lite"  # Gemini API free tier; limits are shown per project in AI Studio
REWRITE_SPACING_S = 6.0  # until the AI Studio RPM is known
SMOKE_MIN_RECALL = 0.947  # 3 points under the 0.977 Recall@5 of rewrite+hybrid+region on the 88 questions (2026-11-04)
