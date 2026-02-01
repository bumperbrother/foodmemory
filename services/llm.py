"""LLM service for intent parsing and structured extraction using Claude."""

import json
import logging
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import anthropic

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Message intent types."""
    LOG_ENTRY = "log_entry"
    ADD_DETAILS = "add_details"
    QUERY_RESTAURANT = "query_restaurant"
    QUERY_GENERAL = "query_general"
    WHAT_TO_EAT = "what_to_eat"
    GREETING = "greeting"
    UNKNOWN = "unknown"


class ParsedLogEntry(BaseModel):
    """Structured log entry extracted from natural language."""
    restaurant_name: str = Field(description="Name of the restaurant")
    dish_name: Optional[str] = Field(default=None, description="Name of the dish ordered")
    sentiment: str = Field(default="neutral", description="Overall sentiment: positive, negative, neutral, or mixed")
    sentiment_score: float = Field(default=0.0, description="Sentiment score from -1.0 (negative) to 1.0 (positive)")
    tags: list[str] = Field(default_factory=list, description="Tags like 'spicy', 'good value', 'slow service'")
    notes: Optional[str] = Field(default=None, description="Additional notes or comments")


class ParsedDetails(BaseModel):
    """Additional details to add to a previous entry."""
    restaurant_name: Optional[str] = Field(default=None, description="Restaurant name if explicitly mentioned")
    dish_name: Optional[str] = Field(default=None, description="Dish name if mentioned")
    notes: Optional[str] = Field(default=None, description="Additional notes or comments")
    sentiment: Optional[str] = Field(default=None, description="Updated sentiment if expressed")
    sentiment_score: Optional[float] = Field(default=None, description="Updated sentiment score")
    tags: list[str] = Field(default_factory=list, description="Additional tags to add")


class ParsedQuery(BaseModel):
    """Parsed query for searching entries."""
    restaurant_name: Optional[str] = Field(default=None, description="Restaurant name to query")
    cuisine: Optional[str] = Field(default=None, description="Cuisine type to filter by")
    sentiment: Optional[str] = Field(default=None, description="Sentiment to filter by")
    search_term: Optional[str] = Field(default=None, description="General search term")


class MessageAnalysis(BaseModel):
    """Complete analysis of a user message."""
    intent: Intent = Field(description="The detected intent of the message")
    confidence: float = Field(default=1.0, description="Confidence in the intent detection (0-1)")
    log_entry: Optional[ParsedLogEntry] = Field(default=None, description="Parsed log entry if intent is LOG_ENTRY")
    details: Optional[ParsedDetails] = Field(default=None, description="Parsed details if intent is ADD_DETAILS")
    query: Optional[ParsedQuery] = Field(default=None, description="Parsed query if intent is QUERY_*")
    clarification_needed: Optional[str] = Field(default=None, description="Question to ask if clarification needed")


SYSTEM_PROMPT = """You are an assistant that helps parse messages for a food/restaurant logging bot.

Your job is to analyze messages and extract structured information. The bot is used by a group of friends to log their restaurant experiences.

## Intent Types:

1. **LOG_ENTRY**: User is logging a new restaurant/food experience OR wants to add an order to a SPECIFIC restaurant
   - Examples: "Pad thai at Siam Station, really good", "Had tacos at Casa Maria - meh", "The burger at Five Guys was amazing"
   - Also use this when user wants to add/save something to a specific restaurant: "Can I add my order to Newport Mesa Bento?", "I want to save my usual at Chipotle"
   - Extract: restaurant_name (REQUIRED), dish_name (optional), sentiment, tags, notes

2. **ADD_DETAILS**: User is adding more details to whatever was JUST logged (no restaurant name mentioned)
   - Examples: "The curry was really spicy", "Also got the spring rolls", "Service was slow though"
   - ONLY use this when the user does NOT mention a restaurant name and is clearly referring to the previous entry
   - If user mentions a restaurant name, use LOG_ENTRY or QUERY_RESTAURANT instead
   - Extract: restaurant_name (if mentioned - important for validation), dish_name, notes, tags, sentiment updates

3. **QUERY_RESTAURANT**: User is asking about a specific restaurant or what they usually get there
   - Examples: "What have we had at Siam Station?", "Show me our visits to Five Guys", "What do I normally get at Newport Mesa Bento?", "What's my usual order at Chipotle?"
   - Extract: restaurant_name

4. **QUERY_GENERAL**: User is asking a general question about their food history
   - Examples: "What Thai places do we like?", "Where did we have good tacos?", "Show me all negative reviews"
   - Extract: cuisine, sentiment, search terms

5. **WHAT_TO_EAT**: User wants a restaurant suggestion
   - Examples: "What should we eat?", "Where should we go for dinner?", "I'm hungry, any suggestions?"

6. **GREETING**: User is greeting the bot
   - Examples: "Hi", "Hello", "Hey bot"

7. **UNKNOWN**: Cannot determine the intent or the message is unrelated

## Important Rules:
- If a message mentions a SPECIFIC restaurant name, it's almost never ADD_DETAILS
- "What do I get at X?" or "What's my usual at X?" = QUERY_RESTAURANT
- "Add my order to X" or "Save my usual at X" = LOG_ENTRY (with that restaurant)
- Only use ADD_DETAILS for follow-up comments with NO restaurant name

## Sentiment Guidelines:
- **positive** (0.5 to 1.0): "amazing", "loved it", "so good", "delicious", "will definitely go back"
- **negative** (-1.0 to -0.5): "terrible", "awful", "never again", "gross", "disappointing"
- **neutral** (-0.2 to 0.2): factual statements, no clear emotion
- **mixed** (-0.5 to 0.5): "food was good but service was slow", conflicting sentiments

## Response Format:
Always respond with valid JSON matching the MessageAnalysis schema. Do not include any other text.

{
  "intent": "log_entry|add_details|query_restaurant|query_general|what_to_eat|greeting|unknown",
  "confidence": 0.0-1.0,
  "log_entry": { ... } // only if intent is log_entry
  "details": { ... } // only if intent is add_details (include restaurant_name if mentioned!)
  "query": { ... } // only if intent is query_*
  "clarification_needed": "..." // if confidence is low
}"""


class LLMService:
    """Service for LLM-based intent parsing and extraction."""

    def __init__(self, api_key: str, max_retries: int = 3):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.max_retries = max_retries

    async def analyze_message(
        self,
        text: str,
        context: Optional[list[dict]] = None,
    ) -> MessageAnalysis:
        """Analyze a message to determine intent and extract structured data.

        Args:
            text: The user's message
            context: Optional list of recent messages for context
                     Format: [{"role": "user"|"assistant", "content": "..."}]

        Returns:
            MessageAnalysis with intent and extracted data
        """
        messages = []

        # Add context messages if provided
        if context:
            for msg in context[-5:]:  # Last 5 messages
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        # Add the current message
        messages.append({
            "role": "user",
            "content": f"Analyze this message: {text}"
        })

        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                )

                # Parse the JSON response
                content = response.content[0].text
                # Clean up potential markdown code blocks
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                content = content.strip()

                data = json.loads(content)

                # Normalize log_entry data if present
                if data.get("log_entry"):
                    data["log_entry"] = self._normalize_log_entry(data["log_entry"])

                # Normalize details data if present
                if data.get("details"):
                    data["details"] = self._normalize_details(data["details"])

                # Convert to Pydantic model
                analysis = MessageAnalysis(
                    intent=Intent(data.get("intent", "unknown")),
                    confidence=data.get("confidence", 1.0),
                    log_entry=ParsedLogEntry(**data["log_entry"]) if data.get("log_entry") else None,
                    details=ParsedDetails(**data["details"]) if data.get("details") else None,
                    query=ParsedQuery(**data["query"]) if data.get("query") else None,
                    clarification_needed=data.get("clarification_needed"),
                )

                return analysis

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse LLM response as JSON (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return MessageAnalysis(
                        intent=Intent.UNKNOWN,
                        confidence=0.0,
                        clarification_needed="I couldn't understand that message. Could you rephrase?"
                    )
            except anthropic.APIError as e:
                logger.error(f"Anthropic API error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error analyzing message (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return MessageAnalysis(
                        intent=Intent.UNKNOWN,
                        confidence=0.0,
                        clarification_needed="Something went wrong. Please try again."
                    )

        # Should not reach here, but just in case
        return MessageAnalysis(
            intent=Intent.UNKNOWN,
            confidence=0.0,
            clarification_needed="Unable to process message."
        )

    def _normalize_log_entry(self, data: dict) -> dict:
        """Normalize log entry data to handle LLM inconsistencies."""
        # Handle sentiment - LLM sometimes returns a float instead of string
        if "sentiment" in data:
            sentiment = data["sentiment"]
            if isinstance(sentiment, (int, float)):
                # Convert numeric sentiment to string
                if sentiment >= 0.5:
                    data["sentiment"] = "positive"
                elif sentiment <= -0.5:
                    data["sentiment"] = "negative"
                elif -0.2 <= sentiment <= 0.2:
                    data["sentiment"] = "neutral"
                else:
                    data["sentiment"] = "mixed"
                # Use the original value as sentiment_score if not set
                if "sentiment_score" not in data or data["sentiment_score"] is None:
                    data["sentiment_score"] = float(sentiment)
            elif sentiment not in ("positive", "negative", "neutral", "mixed"):
                data["sentiment"] = "neutral"

        # Ensure tags is a list
        if "tags" in data and data["tags"] is None:
            data["tags"] = []

        return data

    def _normalize_details(self, data: dict) -> dict:
        """Normalize details data to handle LLM inconsistencies."""
        # Handle sentiment same as log entry
        if "sentiment" in data and data["sentiment"] is not None:
            sentiment = data["sentiment"]
            if isinstance(sentiment, (int, float)):
                if sentiment >= 0.5:
                    data["sentiment"] = "positive"
                elif sentiment <= -0.5:
                    data["sentiment"] = "negative"
                elif -0.2 <= sentiment <= 0.2:
                    data["sentiment"] = "neutral"
                else:
                    data["sentiment"] = "mixed"
                if "sentiment_score" not in data or data["sentiment_score"] is None:
                    data["sentiment_score"] = float(sentiment)

        # Ensure tags is a list
        if "tags" in data and data["tags"] is None:
            data["tags"] = []

        return data

    async def generate_response(self, prompt: str) -> str:
        """Generate a natural language response."""
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I'm having trouble responding right now."

    async def answer_query(self, question: str, data_context: str) -> str:
        """Answer a user's question based on their food data.

        Args:
            question: The user's original question
            data_context: Formatted data from the database

        Returns:
            Natural language response answering the question
        """
        system = """You are a helpful assistant for a food/restaurant logging bot.
The user is asking a question about their saved restaurant experiences.

Based on the data provided, give a friendly, conversational response that directly answers their question.
- Be concise but helpful
- If they ask about their "usual" or "go-to" order, look for patterns in what they've ordered
- If they ask about recommendations, consider sentiment and frequency
- Include specific dish names when relevant
- If there's an exact_order saved, mention that's their saved order
- If the data doesn't have enough info to answer, say so honestly
- Keep response under 3-4 sentences unless more detail is needed"""

        prompt = f"""User's question: {question}

Here's the relevant data from their food log:

{data_context}

Please answer their question based on this data."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error answering query: {e}")
            return "I'm having trouble looking that up right now."
