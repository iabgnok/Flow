from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite


class StateStore:
    def __init__(self, db_path: str = "myflow_state.db"):
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step_id INTEGER DEFAULT 0,
                    context_json TEXT DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS steps (
                    run_id TEXT NOT NULL,
                    step_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    output_json TEXT DEFAULT '{}',
                    context_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_ms INTEGER,
                    PRIMARY KEY (run_id, step_id, created_at)
                )
                """
            )
            await self._migrate_steps_duration_ms(db)
            await db.commit()

    async def _migrate_steps_duration_ms(self, db: aiosqlite.Connection) -> None:
        """旧库无 duration_ms 列时追加（与新建表 DDL 对齐）。"""
        async with db.execute("PRAGMA table_info(steps)") as cur:
            names = {str(row[1]) async for row in cur}
        if "duration_ms" not in names:
            await db.execute("ALTER TABLE steps ADD COLUMN duration_ms INTEGER")

    async def save_run(
        self,
        run_id: str,
        workflow_name: str,
        status: str,
        context: dict[str, Any],
        *,
        current_step_id: int = 0,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                (
                    run_id,
                    workflow_name,
                    status,
                    current_step_id,
                    json.dumps(context, ensure_ascii=False, default=str),
                ),
            )
            await db.commit()

    async def save_checkpoint(self, run_id: str, step_id: int, context: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE runs SET current_step_id=?, context_json=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (step_id, json.dumps(context, ensure_ascii=False, default=str), run_id),
            )
            await db.commit()

    async def save_step(
        self,
        run_id: str,
        step_id: int,
        status: str,
        output: dict[str, Any],
        context: dict[str, Any],
        *,
        duration_ms: int | None = None,
    ) -> None:
        # on_fail 回跳时同一步可能在同一秒内多次记录，须避免 created_at 撞 UNIQUE
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        async with aiosqlite.connect(self.db_path) as db:
            await self._migrate_steps_duration_ms(db)
            await db.execute(
                """
                INSERT INTO steps (run_id, step_id, status, output_json, context_json, created_at, duration_ms)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    step_id,
                    status,
                    json.dumps(output, ensure_ascii=False, default=str),
                    json.dumps(context, ensure_ascii=False, default=str),
                    ts,
                    duration_ms,
                ),
            )
            await db.commit()

    async def load_run(self, run_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return {
                    "run_id": row["run_id"],
                    "workflow_name": row["workflow_name"],
                    "status": row["status"],
                    "current_step_id": row["current_step_id"],
                    "context": json.loads(row["context_json"]),
                    "updated_at": row["updated_at"],
                }

    async def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT run_id, workflow_name, status, updated_at FROM runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def resolve_run_id(self, ref: str) -> str | None:
        """精确匹配 run_id；否则在最近记录中尝试唯一前缀匹配。"""
        r = ref.strip()
        if not r:
            return None
        if await self.load_run(r):
            return r
        rows = await self.list_runs(limit=500)
        candidates = [row["run_id"] for row in rows if str(row["run_id"]).startswith(r)]
        if len(candidates) == 1:
            return str(candidates[0])
        return None

    async def find_run_ids_starting_with(self, prefix: str, *, limit: int = 500) -> list[str]:
        """按 updated_at 倒序的 run_id 中，筛选以前缀开头的 id（用于歧义提示）。"""
        p = prefix.strip()
        if not p:
            return []
        rows = await self.list_runs(limit=limit)
        return [str(r["run_id"]) for r in rows if str(r["run_id"]).startswith(p)]

    async def load_steps(self, run_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT step_id, status, output_json, created_at, duration_ms FROM steps WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ) as cursor:
                rows = [dict(row) async for row in cursor]
        for r in rows:
            try:
                r["output"] = json.loads(r.pop("output_json") or "{}")
            except Exception:
                r["output"] = {}
        return rows

