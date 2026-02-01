"""Food Memory Bot - Main entry point."""

import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import get_config
from services.database import DatabaseService
from services.llm import LLMService, Intent
from services.places import PlacesService
from handlers.log_entry import handle_log_entry, handle_add_details, get_order_conversation_handler
from handlers.what_to_eat import get_what_to_eat_handler, start_what_to_eat
from handlers.query import handle_query, handle_search_command

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    name = user.first_name if user else "there"

    await update.message.reply_text(
        f"Hey {name}! I'm your Food Memory Bot.\n\n"
        "I help you and your friends log restaurant experiences and decide where to eat.\n\n"
        "**What I can do:**\n"
        "• Log a meal: \"Pad thai at Siam Station, really good\"\n"
        "• Ask about a place: \"What have we had at Five Guys?\"\n"
        "• Get suggestions: /whattoeat or \"What should we eat?\"\n"
        "• Search entries: /search tacos\n\n"
        "Just chat naturally - I'll figure out what you mean!",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "**Food Memory Bot Commands:**\n\n"
        "/start - Introduction\n"
        "/whattoeat - Get restaurant suggestions\n"
        "/search <term> - Search your entries\n"
        "/help - This message\n\n"
        "**Natural language examples:**\n"
        "• \"Tacos at Casa Maria, pretty good\"\n"
        "• \"The burger was amazing\"\n"
        "• \"What have we had at Siam Station?\"\n"
        "• \"What Thai places do we like?\"\n"
        "• \"What should we eat tonight?\"\n",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route messages based on LLM intent analysis."""
    config = context.bot_data["config"]
    llm: LLMService = context.bot_data["llm"]

    # Check if chat is allowed
    chat_id = update.effective_chat.id
    if not config.is_chat_allowed(chat_id):
        logger.warning(f"Message from unauthorized chat: {chat_id}")
        return

    text = update.message.text
    if not text:
        return

    # Get conversation context
    messages = context.chat_data.get("messages", [])

    # Add current message to context
    messages.append({"role": "user", "content": text})
    # Keep last 10 messages
    context.chat_data["messages"] = messages[-10:]

    # Analyze the message
    analysis = await llm.analyze_message(text, messages)
    logger.info(f"Intent: {analysis.intent} (confidence: {analysis.confidence})")

    # Handle low confidence
    if analysis.confidence < 0.5 and analysis.clarification_needed:
        await update.message.reply_text(analysis.clarification_needed)
        return

    # Route based on intent
    response = None

    if analysis.intent == Intent.LOG_ENTRY and analysis.log_entry:
        await handle_log_entry(update, context, analysis.log_entry)
        return

    elif analysis.intent == Intent.ADD_DETAILS and analysis.details:
        response = await handle_add_details(update, context, analysis.details)

    elif analysis.intent == Intent.QUERY_RESTAURANT and analysis.query:
        response = await handle_query(update, context, analysis.query)

    elif analysis.intent == Intent.QUERY_GENERAL and analysis.query:
        response = await handle_query(update, context, analysis.query)

    elif analysis.intent == Intent.WHAT_TO_EAT:
        # Start the what to eat flow
        await start_what_to_eat(update, context)
        return

    elif analysis.intent == Intent.GREETING:
        user = update.effective_user
        name = user.first_name if user else "there"
        response = (
            f"Hey {name}! Ready to log some food or find somewhere to eat?\n"
            "Just tell me about your meal or ask /whattoeat for suggestions!"
        )

    elif analysis.intent == Intent.UNKNOWN:
        response = (
            "I'm not sure what you mean. I can help you:\n"
            "• Log a meal: \"Pizza at Joe's, it was great\"\n"
            "• Query a place: \"What have we had at Joe's?\"\n"
            "• Get suggestions: /whattoeat"
        )

    if response:
        # Store bot response in context
        messages.append({"role": "assistant", "content": response})
        context.chat_data["messages"] = messages[-10:]

        await update.message.reply_text(response, parse_mode="Markdown")


async def post_init(application: Application) -> None:
    """Initialize services after bot is created."""
    config = get_config()

    # Initialize database
    db = DatabaseService(config.database_path)
    await db.initialize()

    # Initialize services
    llm = LLMService(config.anthropic_api_key)
    places = PlacesService(config.google_places_api_key, config.default_location_bias)

    # Store in bot_data for handlers
    application.bot_data["config"] = config
    application.bot_data["db"] = db
    application.bot_data["llm"] = llm
    application.bot_data["places"] = places

    logger.info("Services initialized successfully")


async def post_shutdown(application: Application) -> None:
    """Cleanup on shutdown."""
    db = application.bot_data.get("db")
    if db:
        await db.close()
    logger.info("Bot shutdown complete")


def main() -> None:
    """Start the bot."""
    config = get_config()

    # Create application
    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", handle_search_command))

    # Add conversation handlers (must be before general message handler)
    application.add_handler(get_order_conversation_handler())
    application.add_handler(get_what_to_eat_handler())

    # Add general message handler
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Start the bot
    logger.info("Starting Food Memory Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
