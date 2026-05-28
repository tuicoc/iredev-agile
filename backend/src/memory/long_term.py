import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore

from .types import Episode, Fact

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared store factory
# ---------------------------------------------------------------------------

# Process-wide in-memory store singleton.
#
# Used as a fallback when no pg_connection is configured. The interviewer and
# enduser agents instantiate MemoryModule separately but must read each other's
# writes (interviewer records episodes per perspective; both agents recall
# them). Sharing one InMemoryStore at the process level gives them a common
# namespace without requiring Postgres in dev environments.
_in_memory_store_singleton: Optional[InMemoryStore] = None


def _get_in_memory_store() -> InMemoryStore:
    global _in_memory_store_singleton
    if _in_memory_store_singleton is None:
        _in_memory_store_singleton = InMemoryStore()
        logger.info(
            "[memory] Using process-wide InMemoryStore singleton for episodic "
            "/ semantic memory (session-scoped sharing between agents)."
        )
    return _in_memory_store_singleton


def create_store(
    pg_conn_str: Optional[str],
    embed_fn=None,
    dims: int = 1536,
) -> BaseStore:
    """Create the shared LangGraph store.

    Current behavior: always uses the process-wide InMemoryStore singleton.
    Episodes recorded by InterviewerAgent live for one workflow run and are
    consumed by the other agents in the same run; persistence across runs
    is not required for the interview-skip mechanism the singleton supports.

    The pg_conn_str parameter is accepted for forward compatibility with
    long-term memory types that genuinely need Postgres persistence (the
    knowledge base, cross-session profile facts). Wire those through here
    when they are introduced; until then InMemoryStore is correct.
    """
    if pg_conn_str:
        logger.debug(
            "[memory] pg_connection is set but session-scoped memory still "
            "uses the in-memory singleton; remove this branch when long-term "
            "memory types are wired through this factory."
        )
    return _get_in_memory_store()


def reset_in_memory_store() -> None:
    """Discard the in-memory store singleton.

    Useful between test sessions or when starting a new workflow run that
    should not see episodes from a previous run in the same process.
    """
    global _in_memory_store_singleton
    _in_memory_store_singleton = None


# ---------------------------------------------------------------------------
# Episodic Memory — Reviewer Agent (per PR), Sprint Agent
# ---------------------------------------------------------------------------

class EpisodicMemory:
    """Stores and retrieves event episodes per project / entity.

    Each episode records one trigger → decision → outcome cycle.
    Namespace: (project_id, "episodes", entity_id)
    where entity_id is a PR number, sprint ID, etc.
    """

    def __init__(self, store: BaseStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def record(self, entity_id: str, episode: Episode) -> None:
        """Persist one episode under the given entity.

        Args:
            entity_id: PR number, sprint ID, or any unique identifier.
            episode: Episode schema with trigger, decision, outcome.
        """
        namespace = (self._project_id, "episodes", entity_id)
        self._store.put(
            namespace,
            str(uuid.uuid4()),
            {
                "trigger": episode.trigger,
                "decision": episode.decision,
                "outcome": episode.outcome,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def recall(
        self,
        entity_id: str,
        query: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieve past episodes for an entity.

        With embed_fn configured on the store, query enables semantic search.
        Without it, returns the most recent episodes up to limit.

        Args:
            entity_id: Identifier used when recording.
            query: Natural language query for semantic similarity search.
            limit: Max number of episodes to return.

        Returns:
            List of episode dicts.
        """
        namespace = (self._project_id, "episodes", entity_id)
        results = self._store.search(namespace, query=query, limit=limit)
        return [r.value for r in results]


# ---------------------------------------------------------------------------
# Semantic Memory — Interviewer (Consultant Mode), Sprint Agent (backlog profile)
# ---------------------------------------------------------------------------

class SemanticMemory:
    """Stores settled facts and profile data; prevents re-asking known topics.

    Fact topic is used as the key — writing the same topic overwrites the old value,
    which is the intended pattern for profile-style single-source-of-truth storage.
    Namespace: (project_id, "facts", context)
    where context is e.g. "sprint_discussions" or "backlog_profile".
    """

    def __init__(self, store: BaseStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def remember(self, context: str, fact: Fact) -> None:
        """Store or overwrite a settled fact (topic is the dedup key).

        Args:
            context: Logical grouping (e.g. 'sprint_discussions', 'backlog_profile').
            fact: Fact schema with topic and content.
        """
        namespace = (self._project_id, "facts", context)
        self._store.put(namespace, fact.topic, {"topic": fact.topic, "content": fact.content})

    def search(self, context: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve facts semantically similar to query.

        Call before asking a question to check whether the topic was already settled.

        Args:
            context: Logical grouping to search within.
            query: The question or topic to check.
            limit: Max results.

        Returns:
            List of fact dicts; empty list if nothing relevant found.
        """
        namespace = (self._project_id, "facts", context)
        results = self._store.search(namespace, query=query, limit=limit)
        return [r.value for r in results]

    def recall_all(self, context: str) -> List[Dict[str, Any]]:
        """Return every fact in a context (e.g. full backlog profile dump).

        Args:
            context: Logical grouping to dump.

        Returns:
            List of all stored fact dicts.
        """
        namespace = (self._project_id, "facts", context)
        results = self._store.search(namespace, limit=1000)
        return [r.value for r in results]