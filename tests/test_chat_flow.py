import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core import AppException
from app.services import chat_service
from app.schemas.chat import ChatMessageCreate, ChatSessionCreate
from app.services.retrieval_service import RetrievedChunk


NOW = datetime.now(timezone.utc)


def message(message_id, session_id, role, content):
    return SimpleNamespace(
        id=message_id,
        session_id=session_id,
        role=role,
        content=content,
        created_at=NOW,
    )


class ChatFlowTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.user = SimpleNamespace(id=7)
        self.session = SimpleNamespace(id=21, user_id=7, document_id=31)
        self.document = SimpleNamespace(id=31, user_id=7, status="COMPLETED")
        self.question = ChatMessageCreate(
            session_id=21, role="user", content="What was the revenue?"
        )
        self.user_message = message(1, 21, "user", self.question.content)
        self.assistant_message = message(2, 21, "assistant", "Revenue was $10m.")
        self.error_message = message(3, 21, "error", "A safe failure message.")
        self.chunk = RetrievedChunk(
            chunk_id=9,
            document_id=31,
            content="Revenue was $10m.",
            page_number=3,
            chunk_index=2,
            distance=0.1,
            similarity=0.9,
        )

    def test_authorized_session_creation_uses_authenticated_user(self):
        created = SimpleNamespace(
            id=21, user_id=7, document_id=31, title="Report", created_at=NOW,
            updated_at=NOW,
        )
        payload = ChatSessionCreate(user_id=999, document_id=31, title="Report")
        with (
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "create_chat_session", return_value=created) as create,
        ):
            response = chat_service.start_session(self.db, payload, self.user)

        self.assertEqual(response.user_id, self.user.id)
        self.assertEqual(response.document_id, self.document.id)
        self.assertEqual(create.call_args.args[1].user_id, self.user.id)

    def test_rejects_unauthorized_document_for_session_creation(self):
        other_document = SimpleNamespace(id=31, user_id=8)
        with (
            patch.object(chat_service, "get_document_by_id", return_value=other_document),
            patch.object(chat_service, "create_chat_session") as create,
        ):
            with self.assertRaises(AppException) as raised:
                chat_service.start_session(
                    self.db, ChatSessionCreate(user_id=7, document_id=31), self.user
                )

        self.assertEqual(raised.exception.status_code, 404)
        create.assert_not_called()

    def test_rejects_another_users_session(self):
        with patch.object(chat_service, "get_chat_session_by_id", return_value=None):
            with self.assertRaises(AppException) as raised:
                chat_service.add_message(self.db, 21, self.question, self.user)
        self.assertEqual(raised.exception.status_code, 404)

    def test_rejects_empty_question(self):
        payload = ChatMessageCreate(session_id=21, role="user", content="   ")
        with self.assertRaises(AppException) as raised:
            chat_service.add_message(self.db, 21, payload, self.user)
        self.assertEqual(raised.exception.status_code, 422)

    def test_retrieval_uses_session_document_and_success_persists_both_messages(self):
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[self.user_message, self.assistant_message]) as create,
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[self.chunk]) as retrieve,
            patch.object(chat_service, "generate_document_answer", return_value="Revenue was $10m. [Page 3, Chunk 2]"),
        ):
            response = chat_service.add_message(self.db, 21, self.question, self.user)

        self.assertEqual(retrieve.call_args.args[1], self.session.document_id)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(response.answer, "Revenue was $10m. [Page 3, Chunk 2]")
        self.assertEqual(response.user_message.role, "user")
        self.assertEqual(response.assistant_message.role, "assistant")
        self.assertEqual(response.sources[0].page_number, 3)
        self.assertEqual(response.sources[0].chunk_index, 2)
        self.assertIn("Revenue", response.sources[0].excerpt)

    def test_generation_failure_keeps_question_but_does_not_save_assistant(self):
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[self.user_message, self.error_message]) as create,
            patch.object(chat_service, "embed_question", side_effect=RuntimeError("internal")),
        ):
            with self.assertRaises(AppException) as raised:
                chat_service.add_message(self.db, 21, self.question, self.user)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].args[1].role, "user")
        self.assertEqual(create.call_args_list[1].args[1].role, "error")

    def test_empty_gemini_response_does_not_save_assistant(self):
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[self.user_message, self.error_message]) as create,
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[]),
            patch.object(chat_service, "generate_document_answer", side_effect=RuntimeError("empty")),
        ):
            with self.assertRaises(AppException):
                chat_service.add_message(self.db, 21, self.question, self.user)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[1].args[1].role, "error")

    def test_assistant_save_failure_returns_error(self):
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=None),
            patch.object(chat_service, "create_chat_message", side_effect=[self.user_message, RuntimeError("db secret"), self.error_message]),
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[self.chunk]),
            patch.object(chat_service, "generate_document_answer", return_value="Answer"),
        ):
            with self.assertRaises(AppException) as raised:
                chat_service.add_message(self.db, 21, self.question, self.user)
        self.assertEqual(raised.exception.status_code, 500)
        self.assertNotIn("db secret", raised.exception.message)

    def test_retry_reuses_latest_unanswered_question(self):
        with (
            patch.object(chat_service, "get_chat_session_by_id", return_value=self.session),
            patch.object(chat_service, "get_document_by_id", return_value=self.document),
            patch.object(chat_service, "get_latest_unanswered_user_message", return_value=self.user_message),
            patch.object(chat_service, "create_chat_message", return_value=self.assistant_message) as create,
            patch.object(chat_service, "embed_question", return_value=[0.0] * 384),
            patch.object(chat_service, "retrieve_relevant_chunks", return_value=[self.chunk]),
            patch.object(chat_service, "generate_document_answer", return_value="Answer"),
        ):
            chat_service.add_message(self.db, 21, self.question, self.user)
        create.assert_called_once()
        self.assertEqual(create.call_args.args[1].role, "assistant")

    def test_chat_history_endpoint_still_returns_messages(self):
        with patch.object(chat_service, "get_messages_by_session", return_value=[self.user_message]):
            result = chat_service.list_messages(self.db, 21, self.user)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, self.question.content)


if __name__ == "__main__":
    unittest.main()
