"""
test_all_fixes.py - Verify all 4 fixes wired into the rebuilt .pyd modules.
"""
import sys


def main():
    # 1) EXCLUDED_FILE_PATTERNS in mla_constants — TEST_PROMPT/fixture noise
    from tokengram import mla_constants
    patterns = mla_constants.EXCLUDED_FILE_PATTERNS
    new_patterns = ("TEST_PROMPT", "test_prompt", "PROMPT_", "prompts.", "FIXTURE_", "fixture_")
    matched = [p for p in patterns if p in new_patterns]
    print(f"[mla_constants] new noise patterns present: {matched}")
    if len(matched) < 6:
        print("  [FAIL] expected all 6 new patterns to be in EXCLUDED_FILE_PATTERNS")
        return 1

    # 2) Reranker sigmoid normalization
    import math
    from tokengram import search_engine

    class FakeCandidate:
        def __init__(self, content):
            self.content = content
            self.score = 0.0
            self.rank = 0

    class FakeModel:
        def predict(self, pairs):
            # Simulate cross-encoder raw logits (negative + positive)
            return [-8.5, 1.2, -2.0]

    rr = search_engine.Reranker()
    rr.model = FakeModel()
    rr._is_loaded = True

    cands = [FakeCandidate("a"), FakeCandidate("b"), FakeCandidate("c")]
    ranked, conf = rr.rerank("query", cands, top_k=3)

    print(f"[search_engine] reranked scores: {[round(c.score, 4) for c in ranked]}")
    print(f"                confidence: {conf}")

    # All scores must be in [0, 1] — sigmoid range
    if any(c.score < 0.0 or c.score > 1.0 for c in ranked):
        print("  [FAIL] sigmoid produced out-of-range score")
        return 1
    # Top score should correspond to highest raw logit (1.2 -> sigmoid ~0.769)
    top_score_expected = 1.0 / (1.0 + math.exp(-1.2))
    if abs(ranked[0].score - top_score_expected) > 0.001:
        print(f"  [FAIL] top score {ranked[0].score} != expected {top_score_expected}")
        return 1
    if conf != "HIGH_CONFIDENCE":
        print(f"  [FAIL] expected HIGH_CONFIDENCE (top={ranked[0].score:.3f} > 0.3), got {conf}")
        return 1

    # 3) vector_store _canonical_path
    from tokengram import vector_store
    if not hasattr(vector_store, "_canonical_path"):
        print("[vector_store] [FAIL] _canonical_path helper missing")
        return 1
    v1 = vector_store._canonical_path("c:/Users/x/y.py")
    v2 = vector_store._canonical_path("C:\\Users\\x\\y.py")
    print(f"[vector_store] canonical(c:/Users/x/y.py) = {v1!r}")
    print(f"[vector_store] canonical(C:\\Users\\x\\y.py) = {v2!r}")
    if v1 != v2:
        print("  [FAIL] mixed-case/slash variants produced different canonicals")
        return 1

    print("\n[PASS] All 3 .pyd-side fixes verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
