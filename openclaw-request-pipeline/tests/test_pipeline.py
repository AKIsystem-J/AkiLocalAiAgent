from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "py"
sys.path.insert(0, str(ROOT))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "requests").mkdir()
        import oc_pipeline.paths as paths

        paths.workspace_dir = lambda: self.workspace  # type: ignore[method-assign]
        paths.tasks_root = lambda: self.workspace / "requests"  # type: ignore[method-assign]
        self._reload()

    def tearDown(self):
        self.tmp.cleanup()

    def _reload(self):
        for name in list(sys.modules):
            if name.startswith("oc_pipeline") and name != "oc_pipeline.paths":
                del sys.modules[name]
        import oc_pipeline.paths as paths

        paths.workspace_dir = lambda: self.workspace  # type: ignore[method-assign]
        paths.tasks_root = lambda: self.workspace / "requests"  # type: ignore[method-assign]

    def test_new_request_folder_and_md(self):
        from oc_pipeline.engine import ingest

        result = ingest(session_key="slack:test", text="今月の交通費を一覧にして")
        self.assertEqual(result["event"], "new")
        request_id = result["state"]["id"]
        folder = self.workspace / "requests" / request_id
        self.assertTrue(folder.is_dir())
        md = folder / f"{request_id}.md"
        self.assertTrue(md.exists())
        self.assertIn("交通費", md.read_text(encoding="utf-8"))
        self.assertEqual(result["state"]["stage"], "planning")

    def test_plan_then_ok(self):
        from oc_pipeline.engine import capture_plan, ingest

        first = ingest(session_key="slack:t2", text="請求書を整理して")
        cap = capture_plan("slack:t2", "1. 分類する\n2. 合計する")
        self.assertTrue(cap["ok"])
        self.assertEqual(cap["state"]["stage"], "awaiting_approval")
        approved = ingest(session_key="slack:t2", text="OK")
        self.assertEqual(approved["event"], "approved")
        self.assertEqual(approved["state"]["stage"], "executing")

    def test_ng_replans(self):
        from oc_pipeline.engine import capture_plan, ingest

        ingest(session_key="slack:t3", text="売上をまとめて")
        capture_plan("slack:t3", "雑なプラン")
        ng = ingest(session_key="slack:t3", text="NG 月別にして")
        self.assertEqual(ng["event"], "rejected")
        self.assertEqual(ng["state"]["stage"], "replanning")
        self.assertIn("月別", Path(ng["state"]["id"] and (self.workspace / "requests" / ng["state"]["id"] / f"{ng['state']['id']}.md")).read_text(encoding="utf-8"))

    def test_similar_prompt(self):
        from oc_pipeline.engine import ingest

        ingest(session_key="slack:old", text="交通費の領収書を金額クラスで集計して一覧化する")
        again = ingest(session_key="slack:new", text="交通費の領収書を金額クラスで集計して一覧化してほしい")
        self.assertEqual(again["event"], "ask_similar")
        self.assertEqual(again["state"]["stage"], "ask_similar")
        cont = ingest(session_key="slack:new", text="続きで")
        self.assertEqual(cont["event"], "continuation")

    def test_log_rotation_name(self):
        from oc_pipeline.engine import ingest
        from oc_pipeline.logs import append_log, current_log

        result = ingest(session_key="slack:log", text="ログ確認用の依頼です")
        request_id = result["state"]["id"]
        path = append_log(request_id, "hello")
        self.assertTrue(path.endswith(f"{request_id}_0001.log"))
        self.assertEqual(current_log(request_id).name, f"{request_id}_0001.log")

    def test_heartbeat_is_ignored(self):
        from oc_pipeline.engine import ingest

        result = ingest(
            session_key="slack:hb",
            text="Follow the heartbeat monitor scratch context when provided. If nothing needs attention, reply NO_REPLY.",
        )
        self.assertEqual(result["event"], "system")
        self.assertIsNone(result.get("state"))

    def test_greeting_hai_is_not_approval(self):
        from oc_pipeline.engine import capture_plan, ingest

        ingest(session_key="slack:hai", text="請求書を整理して")
        capture_plan("slack:hai", "1. 分類する\n2. 合計する")
        greeting = ingest(session_key="slack:hai", text="はい！繋がってる顔確認だ！")
        self.assertEqual(greeting["event"], "chat")
        self.assertEqual(greeting["state"]["stage"], "awaiting_approval")

    def test_ohayo_is_chat_not_a_request(self):
        from oc_pipeline.engine import ingest

        result = ingest(session_key="slack:ohayo", text="おはよう！繋がってますかー？")
        self.assertEqual(result["event"], "chat")
        self.assertIsNone(result.get("state"))

    def test_done_request_not_reopened_by_greeting(self):
        from oc_pipeline.engine import ingest
        from oc_pipeline.store import set_stage, unbind_session

        first = ingest(session_key="slack:done", text="請求書を整理して")
        set_stage(first["state"]["id"], "done")
        unbind_session("slack:done")
        greeting = ingest(session_key="slack:done", text="おはよう！繋がってますかー？")
        self.assertEqual(greeting["event"], "chat")
        self.assertIsNone(greeting.get("state"))

    def test_ok_during_planning_approves(self):
        from oc_pipeline.engine import ingest

        ingest(session_key="slack:planok", text="請求書を整理して")
        approved = ingest(session_key="slack:planok", text="OK")
        self.assertEqual(approved["event"], "approved")
        self.assertEqual(approved["state"]["stage"], "executing")
        self.assertFalse(approved["state"].get("vision_done"))

    def test_compaction_is_system(self):
        from oc_pipeline.engine import ingest

        result = ingest(
            session_key="slack:compact",
            text="Continue the OpenClaw runtime event.",
        )
        self.assertEqual(result["event"], "system")
        self.assertIsNone(result.get("state"))

    def test_plan_approved_token_continues_executing(self):
        from oc_pipeline.engine import ingest

        ingest(session_key="slack:planapp", text="大阪の市場調査をして")
        ingest(session_key="slack:planapp", text="OK")
        cont = ingest(session_key="slack:planapp", text="PLAN_APPROVED")
        self.assertEqual(cont["event"], "continue_exec")
        self.assertEqual(cont["state"]["stage"], "executing")
        self.assertIn("承認済み", cont["instruction"])

    def test_betsu_during_executing_starts_new(self):
        from oc_pipeline.engine import ingest

        first = ingest(session_key="slack:betsu", text="請求書を整理して")
        ingest(session_key="slack:betsu", text="OK")
        second = ingest(session_key="slack:betsu", text="別件。大阪の市場調査をして")
        self.assertEqual(second["event"], "new")
        self.assertNotEqual(second["state"]["id"], first["state"]["id"])

    def test_peek_resets_when_no_active_request(self):
        from oc_pipeline.engine import peek

        result = peek(session_key="slack:peek", text="おはよう")
        self.assertTrue(result["reset"])
        self.assertEqual(result["action"], "chat")

    def test_repeat_is_noop(self):
        from oc_pipeline.engine import ingest

        ingest(session_key="slack:rep", text="同じ文を二度送るテスト案件")
        second = ingest(session_key="slack:rep", text="同じ文を二度送るテスト案件")
        self.assertEqual(second["event"], "repeat")


if __name__ == "__main__":
    unittest.main()
