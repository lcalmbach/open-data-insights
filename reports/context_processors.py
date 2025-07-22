def ai_disclaimer(request):
    return {
        "AI_DISCLAIMER": (
            "🤖 This text was generated using AI. All quantitative information is based on the dataset referenced in the data source."
        )
    }

def format_instructions(request):
    return {
        "FORMAT_INSTRUCTIONS": (
            "Format the output as plain Markdown. Do not use bold or italic text for emphasis. Avoid using bullet points, numbered lists, or subheadings. Write in concise, complete sentences. Ensure that the structure is clean and easy to read using only paragraphs."
        )
    }