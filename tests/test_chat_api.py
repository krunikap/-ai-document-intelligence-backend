import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user
from app.db import get_db
from app.services import chat_service


NOW = datetime.now(timezone.utc)


def as_message(message_id, role, content):
    return SimpleNamespace(
        id=message_id,
        session_id=21,
        role=role,
        content=content,
        created_at=NOW,
    )


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=7)
        self.db = object()
        self.document = SimpleNamespace(id=31, user_id=7, status="COMPLETED")
        self.session = SimpleNamespace(
            id=21, user_id=7, document_id=31, title="Report",
            created_at=NOW, updated_at=NOW,
        )
        self.error_message = as_message(3, "error", "A safe failure message.")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_swagger_and_openapi_expose_all_phase_seven_paths(self):
        docs = self.client.get("/docs")
        schema = self.client.get("/openapi.json")
        self.assertEqual(docs.status_code, 200)
        self.assertEqual(schema.status_code, 200)
        paths = schema.json()["paths"]
        self.assertIn("/api/v1/documents/{document_id}/chat/sessions", paths)
        self.assertIn("/api/v1/chat/sessions/{session_id}/messages", paths)
        self.assertIn("post", paths["/api/v1/chat/sessions/{session_id}/messages"])
        self.assertIn("get", paths["/api/v1/chat/sessions/{session_id}/messages"])

    def test_create_document_session_endpoint(self):
        with (
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "create_chat_session", return_value=self.session) as create,
        ):
            response = self.client.post(
                "/api/v1/documents/31/chat/sessions", json={"title": "Report"}
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["user_id"], 7)
        self.assertEqual(create.call_args.args[1].document_id, 31)
        self.assertEqual(create.call_args.args[1].user_id, 7)

    def test_list_document_sessions_endpoint(self):
        with (
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_chat_sessions_by_document", return_value=[self.session]),
        ):
            response = self.client.get("/api/v1/documents/31/chat/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

    def test_history_endpoint(self):
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_messages_by_session", return_value=[as_message(1, "user", "Question")]),
        ):
            response = self.client.get("/api/v1/chat/sessions/21/messages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["content"], "Question")

    def test_history_displays_persisted_error_message(self):
        error_message = as_message(
            3, "error", "The AI service couldn't generate an answer."
        )
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_messages_by_session", return_value=[error_message]),
        ):
            response = self.client.get("/api/v1/chat/sessions/21/messages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["role"], "error")
        self.assertIn("couldn't generate an answer", response.json()["data"][0]["content"])

    def test_question_endpoint_returns_answer_and_sources(self):
        user_message = as_message(1, "user", "Question?")
        assistant_message = as_message(2, "assistant", "Answer")
        chunk = SimpleNamespace(
            chunk_id=8, document_id=31, content="Source text", page_number=4,
            chunk_index=2, distance=0.1, similarity=0.9,
        )
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, assistant_message]),
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[chunk]) as retrieve,
            patch.object(chat_service, "generate_document_answer", return_value="Answer [Page 4, Chunk 2]"),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages", json={"content": "Question?"}
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["answer"], "Answer [Page 4, Chunk 2]")
        self.assertEqual(response.json()["data"]["sources"][0]["page_number"], 4)
        self.assertEqual(retrieve.call_args.args[1], self.session.document_id)

    def test_unprocessed_document_is_rejected(self):
        document = SimpleNamespace(id=31, user_id=7, status="PROCESSING")
        with patch.object(chat_service, "get_document_by_id", return_value=document):
            response = self.client.post("/api/v1/documents/31/chat/sessions", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("still in progress", response.json()["message"])

    def test_failed_document_processing_returns_safe_conflict(self):
        document = SimpleNamespace(id=31, user_id=7, status="FAILED")
        with patch.object(chat_service, "get_document_by_id", return_value=document):
            response = self.client.post("/api/v1/documents/31/chat/sessions", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("processing failed", response.json()["message"])

    def test_question_on_failed_document_does_not_start_generation(self):
        document = SimpleNamespace(id=31, user_id=7, status="FAILED")
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=document),
            patch.object(chat_service, "embed_question") as embed,
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages", json={"content": "Question?"}
            )
        self.assertEqual(response.status_code, 409)
        embed.assert_not_called()

    def test_document_not_owned_is_hidden_as_not_found(self):
        other_document = SimpleNamespace(id=31, user_id=8, status="COMPLETED")
        with patch.object(chat_service, "get_document_by_id", return_value=other_document):
            response = self.client.post("/api/v1/documents/31/chat/sessions", json={})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["message"], "Document not found")

    def test_stream_endpoint_emits_chunks_and_done_after_saving_assistant(self):
        user_message = as_message(1, "user", "Question?")
        assistant_message = as_message(2, "assistant", "Answer")
        chunk = SimpleNamespace(
            chunk_id=8, document_id=31, content="Source text", page_number=4,
            chunk_index=2, distance=0.1, similarity=0.9,
        )

        async def fake_stream(question, chunks):
            self.assertEqual(question, "Question?")
            self.assertEqual(chunks, [chunk])
            yield "An"
            yield "swer"

        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, assistant_message]),
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[chunk]),
            patch.object(chat_service, "stream_document_answer", side_effect=lambda *_: fake_stream("Question?", [chunk])),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('event: chunk\ndata: {"text": "An"}\n\n', response.text)
        self.assertIn('event: chunk\ndata: {"text": "swer"}\n\n', response.text)
        self.assertIn('event: done\n', response.text)
        self.assertIn('"page_number": 4', response.text)
        self.assertLess(response.text.index("event: done"), len(response.text))

    def test_stream_generation_failure_sends_error_and_does_not_save_assistant(self):
        user_message = as_message(1, "user", "Question?")

        async def failing_stream(*_):
            yield "partial"
            raise RuntimeError("do not expose this")

        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, self.error_message]) as create,
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[]),
            patch.object(chat_service, "stream_document_answer", side_effect=lambda *_: failing_stream()),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )

        self.assertIn("event: chunk", response.text)
        self.assertIn("event: error", response.text)
        self.assertIn('"code": "ANSWER_GENERATION_FAILED"', response.text)
        self.assertIn("AI service couldn't generate an answer", response.text)
        self.assertNotIn("event: done", response.text)
        self.assertNotIn("do not expose this", response.text)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[1].args[1].role, "error")
        self.assertIn('"role": "error"', response.text)

    def test_stream_embedding_failure_has_specific_safe_message(self):
        user_message = as_message(1, "user", "Question?")
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, self.error_message]) as create,
            patch.object(chat_service, "embed_question", side_effect=RuntimeError("private details")),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        self.assertIn('"code": "QUESTION_EMBEDDING_FAILED"', response.text)
        self.assertIn("prepare your question for document search", response.text)
        self.assertNotIn("private details", response.text)
        self.assertIn('"chat_message": {"id": 3', response.text)
        self.assertEqual(create.call_args_list[1].args[1].role, "error")

    def test_stream_retrieval_failure_has_specific_safe_message(self):
        user_message = as_message(1, "user", "Question?")
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, self.error_message]) as create,
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", side_effect=RuntimeError("private details")),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        self.assertIn('"code": "DOCUMENT_SEARCH_FAILED"', response.text)
        self.assertIn("couldn't search this document", response.text)
        self.assertNotIn("private details", response.text)
        self.assertEqual(create.call_args_list[1].args[1].role, "error")

    def test_stream_empty_generation_and_assistant_persistence_failure_never_emit_done(self):
        user_message = as_message(1, "user", "Question?")

        async def empty_stream(*_):
            if False:
                yield ""

        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, self.error_message]),
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[]),
            patch.object(chat_service, "stream_document_answer", side_effect=lambda *_: empty_stream()),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        self.assertIn("event: error", response.text)
        self.assertNotIn("event: done", response.text)

        async def answer_stream(*_):
            yield "Answer"

        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, RuntimeError("db secret"), self.error_message]),
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[]),
            patch.object(chat_service, "stream_document_answer", side_effect=lambda *_: answer_stream()),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        self.assertIn("event: error", response.text)
        self.assertNotIn("event: done", response.text)
        self.assertNotIn("db secret", response.text)

    def test_stream_rejects_missing_and_unowned_session_before_starting_body(self):
        with patch.object(chat_service, "get_chat_session_by_id", return_value=None):
            response = self.client.post(
                "/api/v1/chat/sessions/999/messages/stream", json={"content": "Question?"}
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["message"], "Chat session not found")

    def test_stream_requires_authentication(self):
        app.dependency_overrides.pop(get_current_user, None)
        try:
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        finally:
            app.dependency_overrides[get_current_user] = lambda: self.user
        self.assertEqual(response.status_code, 401)

    def test_stream_timeout_and_observed_disconnect_do_not_save_assistant(self):
        user_message = as_message(1, "user", "Question?")

        async def timeout_stream(*_):
            raise TimeoutError()
            yield "unreachable"

        common_patches = (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[user_message, self.error_message]),
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[]),
            patch.object(chat_service, "stream_document_answer", side_effect=lambda *_: timeout_stream()),
        )
        with common_patches[0], common_patches[1], common_patches[2], common_patches[3] as create, common_patches[4], common_patches[5], common_patches[6]:
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        self.assertIn("event: error", response.text)
        self.assertNotIn("event: done", response.text)
        self.assertEqual(create.call_count, 2)

        async def answer_stream(*_):
            yield "Answer"

        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", return_value=user_message) as create,
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[]),
            patch.object(chat_service, "stream_document_answer", side_effect=lambda *_: answer_stream()),
            patch("starlette.requests.Request.is_disconnected", new=AsyncMock(return_value=True)),
        ):
            response = self.client.post(
                "/api/v1/chat/sessions/21/messages/stream", json={"content": "Question?"}
            )
        self.assertNotIn("event: done", response.text)
        self.assertEqual(create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
