"""Unit tests for src/context_manager.py — ContextSegment and ContextManager."""
from src.context_manager import ContextManager, ContextSegment
from src.models import AgentState


class TestContextSegment:
    def test_add_content_tracks_relevance(self):
        segment = ContextSegment("research")
        segment.add_content("low relevance text", relevance=0.1)
        segment.add_content("high relevance text", relevance=0.9)

        assert segment.content == ["low relevance text", "high relevance text"]
        assert segment.relevance_scores == {0: 0.1, 1: 0.9}

    def test_get_compressed_prefers_higher_relevance_first(self):
        segment = ContextSegment("research")
        segment.add_content("low relevance", relevance=0.1)
        segment.add_content("high relevance", relevance=0.9)

        compressed = segment.get_compressed(max_tokens=1000)

        assert compressed[0] == "high relevance"
        assert compressed[1] == "low relevance"

    def test_get_compressed_respects_token_budget(self):
        segment = ContextSegment("research")
        segment.add_content("word " * 50, relevance=1.0)  # well over a tiny budget
        segment.add_content("short", relevance=0.5)

        compressed = segment.get_compressed(max_tokens=3)

        # Only the truncated highest-relevance piece should fit; the second
        # entry never gets reached once the budget is exhausted.
        assert len(compressed) == 1


class TestContextManager:
    def test_get_or_create_segment_is_idempotent(self):
        manager = ContextManager()
        first = manager.get_or_create_segment("research")
        second = manager.get_or_create_segment("research")

        assert first is second

    def test_add_to_segment_creates_segment_on_demand(self):
        manager = ContextManager()
        manager.add_to_segment("clinical", "some finding", relevance=0.8)

        assert "clinical" in manager.segments
        assert manager.segments["clinical"].content == ["some finding"]

    def test_get_context_string_empty_when_no_segments(self):
        manager = ContextManager()
        assert manager.get_context_string(max_tokens=1000) == ""

    def test_get_context_string_includes_segment_headers(self):
        manager = ContextManager()
        manager.add_to_segment("research", "finding one")

        result = manager.get_context_string(max_tokens=1000)

        assert "## RESEARCH" in result
        assert "finding one" in result

    def test_should_compress_below_threshold(self):
        manager = ContextManager()
        # context_window_limit=8000, compression_threshold=0.6 by default -> threshold 4800
        assert manager.should_compress(current_tokens=100) is False

    def test_should_compress_at_or_above_threshold(self):
        manager = ContextManager()
        assert manager.should_compress(current_tokens=10_000) is True

    def test_compress_context_noop_below_threshold(self):
        manager = ContextManager()
        state = AgentState(
            task_description="task",
            context_segments={"research": ["short finding"]}
        )

        result = manager.compress_context(state)

        assert result.context_segments == {"research": ["short finding"]}

    def test_compress_context_reduces_segments_above_threshold(self):
        manager = ContextManager()
        # Default context_window_limit=8000 * compression_threshold=0.6 = a
        # 4800-token trigger — each finding here is ~1000+ tokens, well over it.
        long_findings = [f"finding number {i} detail word " * 200 for i in range(20)]
        state = AgentState(
            task_description="task",
            context_segments={"research": long_findings}
        )
        original_token_count = sum(manager.count_tokens(f) for f in long_findings)
        assert manager.should_compress(original_token_count)  # sanity-check the fixture itself

        result = manager.compress_context(state)

        compressed_token_count = sum(manager.count_tokens(f) for f in result.context_segments["research"])
        assert compressed_token_count < original_token_count

    def test_create_checkpoint_captures_state_snapshot(self):
        manager = ContextManager()
        state = AgentState(task_description="task", current_step=2)

        checkpoint = manager.create_checkpoint(state)

        assert checkpoint["current_step"] == 2
        assert checkpoint["todos"] == []
        assert checkpoint["documents"] == {}
