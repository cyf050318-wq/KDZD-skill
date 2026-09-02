import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from complete_task import (
    wrap_html,
    build_update_payload,
    verify_response,
    build_file_src,
    build_image_html,
    build_completion_summary_html,
    upload_screenshot,
)


class TestWrapHtml(unittest.TestCase):
    def test_plain_text_wrapped_in_p(self):
        self.assertEqual(wrap_html("处理完成"), "<p>处理完成</p>")

    def test_html_passthrough(self):
        self.assertEqual(wrap_html("<p>x</p>"), "<p>x</p>")

    def test_html_list_passthrough(self):
        self.assertEqual(wrap_html("<ul><li>a</li></ul>"), "<ul><li>a</li></ul>")

    def test_strips_outer_whitespace_then_wraps(self):
        self.assertEqual(wrap_html("  hello  "), "<p>hello</p>")

    def test_none_returns_empty(self):
        self.assertEqual(wrap_html(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(wrap_html(""), "")


class TestBuildUpdatePayload(unittest.TestCase):
    def test_minimal_payload_has_required_fields(self):
        p = build_update_payload("12167079", 1785399519480, "<p>x</p>")
        self.assertEqual(p["operation"], "UPDATE")
        self.assertEqual(p["entities"][0]["entity_type"], "Task")
        props = p["entities"][0]["properties"]
        self.assertEqual(props["Id"], "12167079")
        self.assertEqual(props["LastUpdateTime"], 1785399519480)
        self.assertEqual(props["CompletionSummary"], "<p>x</p>")
        self.assertNotIn("Status", props)
        self.assertNotIn("CompletionCode", props)
        self.assertNotIn("Comments", props)

    def test_last_update_time_coerced_to_int(self):
        p = build_update_payload("1", "1700000000000", "<p>x</p>")
        self.assertEqual(p["entities"][0]["properties"]["LastUpdateTime"], 1700000000000)
        self.assertIsInstance(p["entities"][0]["properties"]["LastUpdateTime"], int)

    def test_id_stripped(self):
        p = build_update_payload("  12167079  ", 1, "<p>x</p>")
        self.assertEqual(p["entities"][0]["properties"]["Id"], "12167079")

    def test_optional_close_fields_when_provided(self):
        p = build_update_payload("1", 1, "<p>x</p>",
                                 status="Closed", completion_code="Resolvedbyfix",
                                 comments="done")
        props = p["entities"][0]["properties"]
        self.assertEqual(props["Status"], "Closed")
        self.assertEqual(props["CompletionCode"], "Resolvedbyfix")
        self.assertEqual(props["Comments"], "done")


class TestImageHelpers(unittest.TestCase):
    def test_build_file_src_uses_tenant_path(self):
        self.assertEqual(
            build_file_src("1234-5678", tenant="820189321"),
            "../rest/820189321/frs/file-list/1234-5678",
        )

    def test_build_image_html_includes_guid_and_alt(self):
        html = build_image_html("1234-5678", alt="page shot", tenant="820189321")
        self.assertIn('src="../rest/820189321/frs/file-list/1234-5678"', html)
        self.assertIn('alt="page shot"', html)
        self.assertIn("<img", html)

    def test_completion_summary_appends_images_after_text(self):
        html = build_completion_summary_html(
            "处理完成",
            [{"guid": "1234-5678", "filename": "shot.png"}],
            tenant="820189321",
        )
        self.assertTrue(html.startswith("<p>处理完成</p>"))
        self.assertIn('src="../rest/820189321/frs/file-list/1234-5678"', html)
        self.assertIn('alt="shot.png"', html)

    def test_completion_summary_images_only(self):
        html = build_completion_summary_html(
            None,
            [{"guid": "1234-5678", "filename": "shot.png"}],
            tenant="820189321",
        )
        self.assertNotIn("<p></p>", html)
        self.assertIn('src="../rest/820189321/frs/file-list/1234-5678"', html)


class _FakeUploadResponse:
    ok = True
    status_code = 201
    url = "https://example.invalid/rest/820189321/frs/file-list/"
    text = '{"id":"12345678-1234-1234-1234-123456789abc"}'
    headers = {}

    def json(self):
        return {"id": "12345678-1234-1234-1234-123456789abc"}


class TestUploadScreenshot(unittest.TestCase):
    def test_upload_uses_json_compatible_accept_header(self):
        captured = {}

        def fake_post(url, headers, data, timeout):
            captured.update({"url": url, "headers": headers, "data": data, "timeout": timeout})
            return _FakeUploadResponse()

        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "shot.png"
            image.write_bytes(b"not really png but enough for unit test")
            with patch("complete_task.requests.post", side_effect=fake_post):
                ref = upload_screenshot("token", image, base="https://example.invalid", tenant="820189321")

        self.assertEqual(ref["guid"], "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(captured["headers"]["Accept"], "application/json, text/plain, */*")
        self.assertEqual(captured["headers"]["Content-Type"], "image/png")
        self.assertEqual(captured["headers"]["fs_filename"], "shot.png")

class TestVerifyResponse(unittest.TestCase):
    def test_ok_returns_entity(self):
        data = {"meta": {"completion_status": "OK"},
                "entities": [{"completion_status": "OK", "properties": {"Id": "1"}}]}
        ent = verify_response(data)
        self.assertEqual(ent["properties"]["Id"], "1")

    def test_entity_result_list_shape_returns_result(self):
        data = {
            "entity_result_list": [
                {
                    "entity": {"entity_type": "Task", "properties": {"Id": "12167079"}},
                    "completion_status": "OK",
                }
            ],
            "meta": {"completion_status": "OK"},
        }
        ent = verify_response(data)
        self.assertEqual(ent["entity"]["properties"]["Id"], "12167079")

    def test_success_and_completed_accepted(self):
        for cs in ("SUCCESS", "COMPLETED"):
            data = {"meta": {"completion_status": "OK"},
                    "entities": [{"completion_status": cs}]}
            verify_response(data)  # no raise

    def test_meta_not_ok_raises(self):
        data = {"meta": {"completion_status": "FAIL", "errorDetailsList": [{"msg": "boom"}]},
                "entities": []}
        with self.assertRaises(RuntimeError):
            verify_response(data)

    def test_entity_failure_raises(self):
        data = {"meta": {"completion_status": "OK"},
                "entities": [{"completion_status": "FAIL"}]}
        with self.assertRaises(RuntimeError):
            verify_response(data)

    def test_missing_entities_raises(self):
        data = {"meta": {"completion_status": "OK"}, "entities": []}
        with self.assertRaises(RuntimeError):
            verify_response(data)


if __name__ == "__main__":
    unittest.main()


