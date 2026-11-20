"""业务规则自检：不依赖网络与数据库，直接跑 app.services 里的判定逻辑。

运行：cd backend && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from app.services import announcement, dedup, inquiry, page_sample, soft_error
from app.store import store


def sample(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": 999,
        "样本编号": "PS-TEST",
        "来源站点": "市政务服务网",
        "页面地址": "https://example.gov.cn/notice.html",
        "响应ID": "RSP-TEST",
        "采集状态码": "200",
        "页面标题": "未开放",
        "标题": "未开放",
        "正文选择器": "div.content",
        "正文": "2026-11-20 起本窗口停办，相关业务请前往市民中心B区办理。",
        "页尾": "主办单位：市政务服务中心",
    }
    base.update(overrides)
    return base


class StoreResetMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._snapshot = copy.deepcopy(store._tables)

    def tearDown(self) -> None:
        store._tables = self._snapshot


class BodyIntegrityTest(StoreResetMixin):
    def test_empty_body_is_missing_even_with_selector(self) -> None:
        integrity = page_sample.body_integrity(sample(正文=""))
        self.assertFalse(integrity["ok"])
        self.assertIn(page_sample.MISSING_EMPTY_BODY, integrity["reasons"])

    def test_missing_selector_is_missing(self) -> None:
        integrity = page_sample.body_integrity(sample(正文选择器=""))
        self.assertFalse(integrity["ok"])
        self.assertIn(page_sample.MISSING_SELECTOR_MISS, integrity["reasons"])

    def test_missing_status_code_is_missing(self) -> None:
        integrity = page_sample.body_integrity(sample(采集状态码=""))
        self.assertFalse(integrity["ok"])
        self.assertIn(page_sample.MISSING_HTTP_STATUS, integrity["reasons"])

    def test_short_body_is_still_complete(self) -> None:
        integrity = page_sample.body_integrity(sample(正文="2026-11-25起停办。"))
        self.assertTrue(integrity["ok"])
        self.assertLess(integrity["bodyLength"], page_sample.SHORT_BODY_THRESHOLD)


class SoftErrorDetectionTest(StoreResetMixin):
    def test_shared_title_alone_is_valid(self) -> None:
        result = page_sample.detect_soft_error(sample())
        self.assertEqual(result["classification"], "valid")
        self.assertTrue(result["titleShared"])
        self.assertFalse(result["isSoftError"])

    def test_short_body_with_shared_title_is_valid(self) -> None:
        result = page_sample.detect_soft_error(sample(正文="2026-11-25起停办。"))
        self.assertEqual(result["classification"], "valid")
        self.assertTrue(result["shortBody"])

    def test_body_with_date_and_footer_marker_is_conflict(self) -> None:
        result = page_sample.detect_soft_error(sample(页尾="页面正在维护，内容维护中，请稍后重试"))
        self.assertEqual(result["classification"], "conflict")
        self.assertTrue(result["evidenceConflict"])
        self.assertTrue(result["statusOkButErrorPage"])

    def test_placeholder_body_is_soft_error(self) -> None:
        result = page_sample.detect_soft_error(sample(正文="未开放", 页尾=""))
        self.assertEqual(result["classification"], "soft_error")
        self.assertTrue(result["isSoftError"])

    def test_non_200_is_http_error(self) -> None:
        result = page_sample.detect_soft_error(sample(采集状态码="502", 正文="系统繁忙，请稍后重试"))
        self.assertEqual(result["classification"], "http_error")

    def test_evidence_points_back_to_original_fields(self) -> None:
        conflict = sample(页尾="页面正在维护，内容维护中，请稍后重试")
        result = page_sample.detect_soft_error(conflict)
        evidence = page_sample.build_evidence(conflict, result)
        self.assertEqual(evidence["采集状态码"]["value"], "200")
        self.assertEqual(evidence["正文片段"]["field"], "正文")
        self.assertTrue(evidence["正文片段"]["snippet"].startswith("2026-11-20"))
        self.assertTrue(evidence["命中标记"])
        for hit in evidence["命中标记"]:
            self.assertEqual(evidence["原始取值"][hit["field"]], conflict[hit["field"]])
        self.assertTrue(all(evidence["可核对"].values()))


class IsolationScanTest(StoreResetMixin):
    def test_same_template_merges_into_one_record(self) -> None:
        soft_error.scan()
        rows = [row for row in store.rows("soft_error") if row["来源站点"] == "市政务服务网"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["错误模板"], "未开放占位模板")
        self.assertEqual(rows[0]["记录数"], 3)
        self.assertIn("RSP-20261120-002", rows[0]["响应列表"])
        self.assertEqual(rows[0]["冲突响应"], ["RSP-20261120-002"])

    def test_rescan_keeps_code_and_status(self) -> None:
        soft_error.scan()
        row = store.rows("soft_error")[0]
        code, status = row["隔离编号"], "已追问"
        row["status"] = status
        soft_error.scan()
        self.assertEqual(row["隔离编号"], code)
        self.assertEqual(row["status"], status)

    def test_valid_samples_are_not_isolated(self) -> None:
        soft_error.scan()
        isolated = {no for row in store.rows("soft_error") for no in row["样本列表"]}
        self.assertNotIn("PS-0001", isolated)
        self.assertNotIn("PS-0004", isolated)
        self.assertNotIn("PS-0008", isolated)


class DedupSplitTest(StoreResetMixin):
    def test_valid_content_deduped_by_content_key(self) -> None:
        dedup.run_dedup()
        rows = store.rows(dedup.VALID_MODULE)
        p1 = next(row for row in rows if row["样本编号"] == "PS-0001")
        self.assertEqual(p1["状态"], "有效内容（已发布，正文保留）")
        self.assertNotIn("PS-0008", [row["样本编号"] for row in rows])

    def test_blocked_merged_by_template_and_isolated_from_announcements(self) -> None:
        before = copy.deepcopy(store.rows("announcement"))
        soft_error.scan()
        dedup.run_dedup()
        blocked = store.rows(dedup.BLOCKED_MODULE)
        self.assertEqual(len(blocked), 3)
        merged = next(row for row in blocked if row["错误模板"] == "未开放占位模板")
        self.assertEqual(merged["记录数"], 3)
        self.assertEqual(store.rows("announcement"), before)

    def test_missing_body_never_becomes_valid_content(self) -> None:
        dedup.run_dedup()
        sample_numbers = {row["样本编号"] for row in store.rows(dedup.VALID_MODULE)}
        self.assertNotIn("PS-0005", sample_numbers)


class AnnouncementTest(StoreResetMixin):
    def test_publish_from_preserved_dedup_keeps_original_body(self) -> None:
        dedup.run_dedup()
        original = copy.deepcopy(store.find("announcement", 1))
        row = next(row for row in store.rows(dedup.VALID_MODULE) if row["样本编号"] == "PS-0001")
        entry, message = announcement.AnnouncementService().publish_from_dedup(dedup_id=row["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["公告编号"], "ANNO-0001")
        self.assertEqual(store.find("announcement", 1), original)
        self.assertIn("保留原记录", message)

    def test_publish_rejects_isolated_sample(self) -> None:
        soft_error.scan()
        store.rows(dedup.VALID_MODULE).append({
            "id": 999,
            "去重键": "fake",
            "来源站点": "市政务服务网",
            "标题": "社保窗口停办公告",
            "正文": "2026-11-20 起本窗口停办，相关业务请前往市民中心B区办理。",
            "样本编号": "PS-0002",
            "响应ID": "RSP-20261120-002",
        })
        entry, message = announcement.AnnouncementService().publish_from_dedup(dedup_id=999)
        self.assertIsNone(entry)
        self.assertIn("已被隔离", message)

    def test_publish_rejects_empty_body(self) -> None:
        store.rows(dedup.VALID_MODULE).append({
            "id": 998,
            "去重键": "fake-empty",
            "来源站点": "市人社局",
            "标题": "空公告",
            "正文": "   ",
            "样本编号": "PS-0005",
        })
        entry, message = announcement.AnnouncementService().publish_from_dedup(dedup_id=998)
        self.assertIsNone(entry)
        self.assertIn("正文为空", message)

    def test_verify_detects_tampered_body(self) -> None:
        check, message = announcement.AnnouncementService().verify(1)
        self.assertTrue(check["一致"])
        store.find("announcement", 1)["正文"] += "补一句"
        check, message = announcement.AnnouncementService().verify(1)
        self.assertFalse(check["一致"])
        self.assertIn("不一致", message)

    def test_day_summary_reports_adopted_announcement_and_inquiry_target(self) -> None:
        soft_error.scan()
        summary = announcement.AnnouncementService().day_summary("2026-11-20")
        self.assertEqual(summary["采用公告"]["公告编号"], "ANNO-0001")
        self.assertEqual(summary["采用公告"]["来源响应"], "RSP-20261118-001")
        self.assertTrue(summary["核对"]["一致"])
        targets = {item["响应ID"] for item in summary["追问"]}
        self.assertEqual(targets, {"RSP-20261120-002"})


class InquiryTest(StoreResetMixin):
    def test_inquiry_must_target_response_in_isolation(self) -> None:
        soft_error.scan()
        code = next(row["隔离编号"] for row in store.rows("soft_error") if row["来源站点"] == "市政务服务网")
        entry, message = inquiry.InquiryService().raise_for_isolation(code, "RSP-20261118-001")
        self.assertIsNone(entry)
        self.assertIn("不属于隔离记录", message)
        entry, message = inquiry.InquiryService().raise_for_isolation(code, "RSP-20261120-002")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["响应ID"], "RSP-20261120-002")
        self.assertEqual(entry["正文片段"][:10], "2026-11-20")


if __name__ == "__main__":
    unittest.main()
