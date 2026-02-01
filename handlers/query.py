"""Handler for querying saved food entries."""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from services.llm import ParsedQuery, LLMService
from services.database import DatabaseService

logger = logging.getLogger(__name__)


async def handle_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed: ParsedQuery,
    original_question: str = None,
) -> str:
    """Handle queries about saved entries.

    Args:
        update: Telegram update
        context: Bot context with services
        parsed: Parsed query from LLM
        original_question: The user's original question text

    Returns:
        Response message with query results
    """
    db: DatabaseService = context.bot_data["db"]
    llm: LLMService = context.bot_data["llm"]

    # Get the original question from the message if not provided
    if original_question is None:
        original_question = update.message.text if update.message else "What do you have?"

    # Restaurant-specific query
    if parsed.restaurant_name:
        return await _query_restaurant(db, llm, parsed.restaurant_name, original_question)

    # General search
    entries = await db.search_entries(
        cuisine=parsed.cuisine,
        sentiment=parsed.sentiment,
        search_term=parsed.search_term,
        limit=15,
    )

    if not entries:
        query_desc = _describe_query(parsed)
        return f"I don't have any entries{query_desc} yet. Try logging some experiences first!"

    # Format data for LLM
    data_context = _format_entries_for_llm(entries)

    # Get natural language response
    return await llm.answer_query(original_question, data_context)


async def _query_restaurant(
    db: DatabaseService,
    llm: LLMService,
    restaurant_name: str,
    original_question: str,
) -> str:
    """Query entries for a specific restaurant."""
    restaurant = await db.find_restaurant_by_name(restaurant_name)

    if not restaurant:
        return f"I don't have any records for '{restaurant_name}'. Is the name spelled correctly?"

    entries = await db.get_entries_for_restaurant(restaurant.id, limit=15)

    if not entries:
        return f"I found {restaurant.name} in the database, but there are no logged visits yet!"

    # Build data context for LLM
    data_context = f"Restaurant: {restaurant.name}\n"
    if restaurant.cuisine:
        data_context += f"Cuisine: {restaurant.cuisine}\n"
    if restaurant.address:
        data_context += f"Address: {restaurant.address}\n"

    data_context += f"\nTotal visits logged: {len(entries)}\n\nEntries:\n"

    for entry in entries:
        data_context += f"\n- Date: {entry.created_at[:10] if entry.created_at else 'Unknown'}\n"
        data_context += f"  User: {entry.user_name or 'Unknown'}\n"
        if entry.dish:
            data_context += f"  Dish: {entry.dish}\n"
        if entry.exact_order:
            data_context += f"  Saved order: {entry.exact_order}\n"
        if entry.sentiment:
            data_context += f"  Sentiment: {entry.sentiment}\n"
        if entry.notes:
            data_context += f"  Notes: {entry.notes}\n"
        if entry.tags:
            data_context += f"  Tags: {', '.join(entry.tags)}\n"

    # Get natural language response
    return await llm.answer_query(original_question, data_context)


def _format_entries_for_llm(entries: list) -> str:
    """Format entries as context for the LLM."""
    data_context = f"Total entries found: {len(entries)}\n\n"

    for entry in entries:
        data_context += f"- Restaurant: {entry.restaurant_name or 'Unknown'}\n"
        data_context += f"  Date: {entry.created_at[:10] if entry.created_at else 'Unknown'}\n"
        data_context += f"  User: {entry.user_name or 'Unknown'}\n"
        if entry.dish:
            data_context += f"  Dish: {entry.dish}\n"
        if entry.exact_order:
            data_context += f"  Saved order: {entry.exact_order}\n"
        if entry.sentiment:
            data_context += f"  Sentiment: {entry.sentiment}\n"
        if entry.notes:
            data_context += f"  Notes: {entry.notes}\n"
        if entry.tags:
            data_context += f"  Tags: {', '.join(entry.tags)}\n"
        data_context += "\n"

    return data_context


def _describe_query(parsed: ParsedQuery) -> str:
    """Create a natural language description of the query."""
    parts = []

    if parsed.cuisine:
        parts.append(f"for {parsed.cuisine} food")
    if parsed.sentiment:
        parts.append(f"with {parsed.sentiment} reviews")
    if parsed.search_term:
        parts.append(f"matching '{parsed.search_term}'")

    if parts:
        return " " + " ".join(parts)
    return ""


async def handle_search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /search command."""
    db: DatabaseService = context.bot_data["db"]
    llm: LLMService = context.bot_data["llm"]

    # Get search term from command args
    if not context.args:
        await update.message.reply_text(
            "Usage: /search <term>\n"
            "Example: /search tacos"
        )
        return

    search_term = " ".join(context.args)
    entries = await db.search_entries(search_term=search_term, limit=15)

    if not entries:
        await update.message.reply_text(f"No entries found matching '{search_term}'")
        return

    # Format data and get LLM response
    data_context = _format_entries_for_llm(entries)
    question = f"What do we have that matches '{search_term}'?"
    response = await llm.answer_query(question, data_context)

    await update.message.reply_text(response)
