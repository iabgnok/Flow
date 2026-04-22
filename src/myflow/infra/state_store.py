from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite


class StateStore:
    def __init__(self, db_path: str = "myflow_state.db"):
        self.db_path = db_path

    # 初始化数据库表结构（如果尚未存在）
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



    # save_run 负责 run 生命周期节点写入（run表）
        # 启动时：
            # 写 running（current_step_id=0）。
        # 中断时：
            # 再写一次 running（带当前 step 游标）。
        # 完成时
            # 异常失败时：在 runner.py:263 写 failed。
            # 正常完成时：在 runner.py:276 写 completed。
    # save_checkpoint 负责步骤前进度快照（runs表）
        # 只更新 runs 表的 current_step_id、context_json、updated_at。
    # save_step 负责步骤执行结果明细。（steps表）
        # 成功分支调 save_step，status 为 success。
        # 失败分支调 save_step，status 为 failed。

    # 保存或更新运行记录；如果 run_id 已存在则覆盖（适用于恢复场景）
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

    # 更新运行状态和上下文（适用于每步完成后的 checkpoint）
    # 与save_run 的区别在于：不修改 workflow_name，且仅更新 current_step_id、context_json 和 updated_at
    # 都是针对运行层面的记录；步骤层面的记录由 save_step 负责
    async def save_checkpoint(self, run_id: str, step_id: int, context: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE runs SET current_step_id=?, context_json=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (step_id, json.dumps(context, ensure_ascii=False, default=str), run_id),
            )
            await db.commit()

    # 保存步骤记录；同一 run_id 和 step_id 的记录允许多条
    # （on_fail 回跳时会重复记录同一步），因此不设 UNIQUE 约束 
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

    # 先做 run_id 精确匹配。
    # 精确失败后，在最近 500 条里做“前缀唯一匹配”。
    # 仅当候选唯一时返回该 run_id，否则返回 None（避免歧义）。
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

    # 读取某 run 的全部步骤记录，按 created_at 排序。
    # 把每条记录的 output_json 解析为 output 字段。
    # 解析失败时兜底为空字典，避免因为坏数据导致整体读取失败。
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

