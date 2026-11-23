import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy.dialects import postgresql

from app.services.document_processing_service import EMBEDDING_DIMENSIONS
from app.services.retrieval_service import retrieve_relevant_chunks


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.embedding = [0.0] * EMBEDDING_DIMENSIONS

    def run_query_with_rows(self, rows, top_k=5):
        self.db.execute.return_value.all.return_value = rows
        results = retrieve_relevant_chunks(
            self.db, 12, self.embedding, top_k=top_k
        )
        statement = self.db.execute.call_args.args[0]
        return results, statement.compile(dialect=postgresql.dialect())

    def test_returns_rows_in_query_ranking_with_similarity(self):
        self.db.execute.return_value.all.return_value = [
            SimpleNamespace(
                chunk_id=8, document_id=12, content="closest", page_number=2,
                chunk_index=1, distance=0.1,
            ),
            SimpleNamespace(
                chunk_id=4, document_id=12, content="next", page_number=1,
                chunk_index=0, distance=0.3,
            ),
        ]
        results = retrieve_relevant_chunks(self.db, 12, self.embedding)

        self.assertEqual([result.content for result in results], ["closest", "next"])
        self.assertAlmostEqual(results[0].similarity, 0.9)
        self.assertAlmostEqual(results[1].similarity, 0.7)
        self.assertEqual(results[0].chunk_id, 8)
        self.assertEqual(results[0].page_number, 2)
        self.assertEqual(results[0].chunk_index, 1)

    def test_limits_query_to_top_k(self):
        _, compiled = self.run_query_with_rows([], top_k=3)
        self.assertIn("LIMIT %(param_1)s", str(compiled))
        self.assertEqual(compiled.params["param_1"], 3)

    def test_query_excludes_null_embeddings_and_filters_exact_document(self):
        _, compiled = self.run_query_with_rows([])
        sql = str(compiled)
        self.assertIn("document_chunks.document_id =", sql)
        self.assertIn("document_chunks.embedding IS NOT NULL", sql)
        self.assertEqual(compiled.params["document_id_1"], 12)

    def test_empty_matching_document_returns_no_results(self):
        results, _ = self.run_query_with_rows([])
        self.assertEqual(results, [])

    def test_never_returns_other_document_rows(self):
        # The database predicate is the isolation boundary; another document's
        # rows must not be selected even when their vectors are a closer match.
        _, compiled = self.run_query_with_rows([])
        self.assertIn("document_chunks.document_id =", str(compiled))
        self.assertEqual(compiled.params["document_id_1"], 12)

    def test_rejects_wrong_embedding_dimension(self):
        with self.assertRaisesRegex(ValueError, "384 values"):
            retrieve_relevant_chunks(self.db, 12, [0.0, 1.0])
        self.db.execute.assert_not_called()

    def test_rejects_non_finite_embedding_values(self):
        embedding = self.embedding.copy()
        embedding[3] = float("inf")
        with self.assertRaisesRegex(ValueError, "finite"):
            retrieve_relevant_chunks(self.db, 12, embedding)
        self.db.execute.assert_not_called()

    def test_rejects_invalid_top_k(self):
        for top_k in (0, 21, -1, 1.5, True):
            with self.subTest(top_k=top_k):
                with self.assertRaisesRegex(ValueError, "top_k"):
                    retrieve_relevant_chunks(
                        self.db, 12, self.embedding, top_k=top_k
                    )
        self.db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
