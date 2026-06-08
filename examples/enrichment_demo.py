from pprint import pprint

from autoresearch.enrichment import run_demo


if __name__ == "__main__":
    result = run_demo("OpenAI", "https://openai.com")
    pprint(result)
