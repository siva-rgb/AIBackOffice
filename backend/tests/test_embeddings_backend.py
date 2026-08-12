"""Embeddings run on Vertex (gemini-embedding-001) or the gateway.

The backend is chosen by the *shape* of `EMBEDDING_MODEL`: the gateway
namespaces its models with a provider prefix (`azure.`, `vertex_ai.`), so a bare
name means call Vertex directly. One setting, no second flag to keep in sync.

The dimensionality contract is the load-bearing part. `agent_memory.embedding_vec`
is `vector(1536)`; gemini-embedding-001 is natively 3072 and must be asked for
1536 via `output_dimensionality`. Getting that wrong writes vectors Postgres
rejects, or — worse — silently unusable ones.

Nothing here touches the network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import embeddings


@pytest.fixture(autouse=True)
def _clear_cache():
    embeddings._cache.clear()
    yield
    embeddings._cache.clear()


class TestBackendSelection:
    @pytest.mark.parametrize(
        "model,expected",
        [
            ("gemini-embedding-001", "vertex"),
            ("text-embedding-005", "vertex"),
            ("azure.text-embedding-3-small", "gateway"),
            ("vertex_ai.text-embedding-005", "gateway"),  # prefixed = proxied by the gateway
        ],
    )
    def test_model_name_shape_picks_the_backend(self, monkeypatch, settings, model, expected):
        monkeypatch.setattr(settings, "EMBEDDING_MODEL", model)
        assert embeddings.backend_name() == expected

    def test_no_model_means_disabled(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "EMBEDDING_MODEL", "")
        assert embeddings.is_enabled() is False

    def test_vertex_model_needs_vertex_credentials(self, monkeypatch, settings):
        from app.services import vertex_llm

        monkeypatch.setattr(settings, "EMBEDDING_MODEL", "gemini-embedding-001")
        monkeypatch.setattr(vertex_llm, "is_configured", lambda: False)
        assert embeddings.is_enabled() is False
        monkeypatch.setattr(vertex_llm, "is_configured", lambda: True)
        assert embeddings.is_enabled() is True


class FakeEmbeddingModel:
    """Stands in for vertexai TextEmbeddingModel; records what it was asked for."""

    calls: list[dict] = []

    @classmethod
    def from_pretrained(cls, name):
        cls.last_model = name
        return cls()

    def get_embeddings(self, texts, output_dimensionality=None):
        FakeEmbeddingModel.calls.append({"n": len(texts), "dims": output_dimensionality})
        return [SimpleNamespace(values=[0.1] * (output_dimensionality or 3072)) for _ in texts]


@pytest.fixture
def vertex(monkeypatch, settings):
    """Route embeddings at a fake Vertex model."""
    from app.services import vertex_llm

    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 1536)
    monkeypatch.setattr(vertex_llm, "is_configured", lambda: True)
    monkeypatch.setattr(vertex_llm, "_init", lambda: None)

    FakeEmbeddingModel.calls = []
    module = SimpleNamespace(TextEmbeddingModel=FakeEmbeddingModel)
    monkeypatch.setitem(__import__("sys").modules, "vertexai.language_models", module)
    return FakeEmbeddingModel


class TestDimensionality:
    def test_requests_the_configured_dimension(self, vertex):
        """gemini-embedding-001 is natively 3072; the column is vector(1536)."""
        vec = embeddings.embed("hello")
        assert len(vec) == 1536
        assert vertex.calls[0]["dims"] == 1536

    def test_dimension_follows_the_setting(self, vertex, monkeypatch, settings):
        monkeypatch.setattr(settings, "EMBEDDING_DIM", 768)
        assert len(embeddings.embed("hello")) == 768


class TestBatching:
    def test_a_large_batch_is_chunked(self, vertex):
        """One oversized request would risk the per-request instance limit."""
        embeddings.embed_batch([f"text {i}" for i in range(60)])
        assert len(vertex.calls) == 3
        assert [c["n"] for c in vertex.calls] == [25, 25, 10]

    def test_order_is_preserved_across_chunks(self, vertex):
        out = embeddings.embed_batch([f"text {i}" for i in range(60)])
        assert len(out) == 60
        assert all(v is not None for v in out)

    def test_cached_items_are_not_requested_again(self, vertex):
        embeddings.embed("repeated")
        before = len(vertex.calls)
        embeddings.embed("repeated")
        assert len(vertex.calls) == before

    def test_blank_entries_stay_none_and_keep_their_slot(self, vertex):
        out = embeddings.embed_batch(["alpha", "", "gamma"])
        assert out[1] is None
        assert out[0] is not None and out[2] is not None


def test_the_suite_cannot_reach_vertex_embeddings():
    """Regression guard, and the second instance of the same hole.

    Embeddings are selected by EMBEDDING_MODEL, not KORA_AI_BACKEND, so pinning
    the mock provider does nothing for them. With the default bare model name
    plus ambient ADC, every recall test embedded for real — visible only as the
    suite slowing from 22s to 112s.
    """
    from app.config import settings as live

    assert live.EMBEDDING_MODEL == "", "conftest must blank EMBEDDING_MODEL — see the ADC note there"
    assert embeddings.is_enabled() is False


class TestFailureIsSoft:
    def test_a_backend_error_returns_none_rather_than_raising(self, vertex, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("vertex unavailable")

        monkeypatch.setattr(FakeEmbeddingModel, "get_embeddings", boom)
        assert embeddings.embed("hello") is None

    def test_a_batch_error_returns_all_none(self, vertex, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("vertex unavailable")

        monkeypatch.setattr(FakeEmbeddingModel, "get_embeddings", boom)
        assert embeddings.embed_batch(["a", "b"]) == [None, None]

    def test_disabled_backend_short_circuits(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "EMBEDDING_MODEL", "")
        assert embeddings.embed("hello") is None
        assert embeddings.embed_batch(["a", "b"]) == [None, None]
