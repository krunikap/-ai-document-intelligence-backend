import math
import unittest
from unittest.mock import patch

from app.services import embedding_service
from app.services.document_processing_service import EMBEDDING_DIMENSIONS


class EmbedQuestionTests(unittest.TestCase):
    def test_valid_sample_question_returns_one_embedding(self):
        vector = [1.0 / math.sqrt(EMBEDDING_DIMENSIONS)] * EMBEDDING_DIMENSIONS
        with patch.object(embedding_service, "embed_texts", return_value=[vector]) as embed:
            result = embedding_service.embed_question("What is in this document?")

        embed.assert_called_once_with(["What is in this document?"])
        self.assertIsInstance(result, list)
        self.assertTrue(all(isinstance(value, float) for value in result))

    def test_rejects_whitespace_only_question(self):
        with patch.object(embedding_service, "embed_texts") as embed:
            with self.assertRaisesRegex(ValueError, "whitespace-only"):
                embedding_service.embed_question(" \n\t ")

        embed.assert_not_called()

    def test_validates_vector_dimension(self):
        with patch.object(embedding_service, "embed_texts", return_value=[[0.1, 0.2]]):
            with self.assertRaisesRegex(ValueError, "384 values"):
                embedding_service.embed_question("A question")

    def test_validates_finite_values(self):
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = float("nan")
        with patch.object(embedding_service, "embed_texts", return_value=[vector]):
            with self.assertRaisesRegex(ValueError, "finite"):
                embedding_service.embed_question("A question")

    def test_embedding_is_normalized(self):
        vector = [1.0 / math.sqrt(EMBEDDING_DIMENSIONS)] * EMBEDDING_DIMENSIONS
        with patch.object(embedding_service, "embed_texts", return_value=[vector]):
            result = embedding_service.embed_question("A question")

        norm = math.sqrt(sum(value * value for value in result))
        self.assertAlmostEqual(norm, 1.0, delta=1e-6)

    def test_reuses_existing_embedding_implementation(self):
        vector = [1.0 / math.sqrt(EMBEDDING_DIMENSIONS)] * EMBEDDING_DIMENSIONS
        with (
            patch.object(embedding_service, "embed_texts", return_value=[vector]) as embed,
            patch("app.services.document_processing_service.SentenceTransformer") as model_init,
        ):
            embedding_service.embed_question("A question")

        embed.assert_called_once()
        model_init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
