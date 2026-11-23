from app.services.llm_service import generate_answer


if __name__ == "__main__":
    prompt = "Explain what an API is in three simple sentences."

    try:
        answer = generate_answer(prompt)
        print("Gemini response:")
        print(answer)
    except Exception as exc:
        print(f"Gemini request failed: {type(exc).__name__}: {exc}")