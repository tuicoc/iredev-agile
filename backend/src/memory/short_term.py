from typing import List, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class ConversationBuffer:
    """Session-scoped message buffer — wiped once an artifact is complete.

    No framework dependency; plain Python list wrapped for convenience.
    Mirrors LangChain message format so it feeds directly into llm.invoke().
    """

    def __init__(self, system_prompt: str = "") -> None:
        self._history: List[BaseMessage] = []
        if system_prompt:
            self._history.append(SystemMessage(content=system_prompt))

    def add_user(self, content: str) -> None:
        self._history.append(HumanMessage(content=content))

    def add_assistant(self, content: str) -> None:
        self._history.append(AIMessage(content=content))

    def get(self) -> List[BaseMessage]:
        return list(self._history)

    def clear(self) -> None:
        system = [m for m in self._history if isinstance(m, SystemMessage)]
        self._history = system


def _build_pool(pg_conn_str: str, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Build a ConnectionPool with the kwargs LangGraph Postgres backends expect."""
    dsn = pg_conn_str.replace("postgresql+psycopg://", "postgresql://")
    return ConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=True,
    )


def create_langgraph_postgres(
    pg_conn_str: str,
    min_size: int = 1,
    max_size: int = 10,
) -> Tuple[PostgresSaver, PostgresStore, ConnectionPool]:
    """Build a Postgres-backed checkpointer + store sharing one pool.

    The pool is opened eagerly and both backends run their idempotent
    setup() so required tables/indexes exist. The pool is returned so the
    caller can keep a reference for the server lifetime (and close it on
    shutdown).

    Scope each session via thread_id: {"configurable": {"thread_id": "..."}}.
    """
    pool = _build_pool(pg_conn_str, min_size=min_size, max_size=max_size)
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    store = PostgresStore(pool)
    store.setup()
    return checkpointer, store, pool
