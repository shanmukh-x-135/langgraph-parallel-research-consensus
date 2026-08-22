import json

from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.research.models import AgentName, Claim, ExtractedClaims, SearchSource


class ClaimExtractor:
    def __init__(self, settings: Settings) -> None:
        api_key = settings.openai_api_key.get_secret_value()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for live research")
        model = ChatOpenAI(
            model=settings.agent_model,
            api_key=api_key,
            max_completion_tokens=settings.agent_max_tokens,
            timeout=settings.agent_timeout_seconds,
            max_retries=1,
        )
        self._structured_model = model.with_structured_output(
            ExtractedClaims,
            method="json_schema",
        )

    async def extract(
        self,
        query: str,
        agent: AgentName,
        strategy: str,
        sources: list[SearchSource],
    ) -> list[Claim]:
        if not sources:
            return []

        source_payload = [source.model_dump(mode="json") for source in sources]
        prompt = (
            "Extract concise, independently checkable claims that answer the research question. "
            "Use only the supplied sources. Every claim must include a short evidence excerpt or "
            "paraphrase and one or more exact source URLs from the supplied list. "
            "Do not invent URLs.\n\n"
            f"Research question: {query}\n"
            f"Agent: {agent.value}\n"
            f"Strategy: {strategy}\n"
            f"Sources: {json.dumps(source_payload)}"
        )
        extracted = await self._structured_model.ainvoke(prompt)
        if not isinstance(extracted, ExtractedClaims):
            extracted = ExtractedClaims.model_validate(extracted)

        allowed_urls = {str(source.url) for source in sources}
        valid_claims: list[Claim] = []
        for claim in extracted.claims:
            cited_urls = [url for url in claim.source_urls if str(url) in allowed_urls]
            if cited_urls:
                valid_claims.append(claim.model_copy(update={"source_urls": cited_urls}))
        return valid_claims
