"""Handler for 'what to eat' decision flow."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from services.database import DatabaseService

logger = logging.getLogger(__name__)

# Conversation states
SELECTING_CUISINE = 0
CONFIRMING = 1

# Callback data prefixes
CUISINE_PREFIX = "cuisine:"
ACCEPT = "accept"
REJECT = "reject"
CANCEL = "cancel"
ANY_CUISINE = "any"


async def start_what_to_eat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Start the what to eat flow."""
    db: DatabaseService = context.bot_data["db"]

    # Get distinct cuisines from saved restaurants
    cuisines = await db.get_distinct_cuisines()

    if not cuisines:
        await update.message.reply_text(
            "You haven't saved any restaurants yet! "
            "Try logging some food experiences first, like:\n"
            "\"Pad thai at Siam Station, really good\""
        )
        return ConversationHandler.END

    # Build cuisine buttons (2 per row)
    keyboard = []
    row = []
    for cuisine in cuisines[:8]:  # Limit to 8 cuisines
        row.append(InlineKeyboardButton(cuisine, callback_data=f"{CUISINE_PREFIX}{cuisine}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Add "Any" and "Cancel" buttons
    keyboard.append([
        InlineKeyboardButton("🎲 Any cuisine", callback_data=f"{CUISINE_PREFIX}{ANY_CUISINE}"),
    ])
    keyboard.append([
        InlineKeyboardButton("❌ Cancel", callback_data=CANCEL),
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Initialize rejected restaurants list
    context.chat_data["rejected_restaurants"] = []

    await update.message.reply_text(
        "What kind of food are you in the mood for?",
        reply_markup=reply_markup,
    )

    return SELECTING_CUISINE


async def handle_cuisine_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Handle cuisine selection and suggest a restaurant."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == CANCEL:
        await query.edit_message_text("No problem! Let me know when you're ready to eat.")
        return ConversationHandler.END

    # Extract cuisine
    cuisine = data.replace(CUISINE_PREFIX, "")
    if cuisine == ANY_CUISINE:
        cuisine = None

    context.chat_data["selected_cuisine"] = cuisine

    return await suggest_restaurant(update, context)


async def suggest_restaurant(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Suggest a random positive restaurant."""
    db: DatabaseService = context.bot_data["db"]
    query = update.callback_query

    cuisine = context.chat_data.get("selected_cuisine")
    rejected = context.chat_data.get("rejected_restaurants", [])

    result = await db.get_random_positive_restaurant(
        cuisine=cuisine,
        exclude_ids=rejected,
    )

    if not result:
        cuisine_text = f" {cuisine}" if cuisine else ""
        await query.edit_message_text(
            f"I don't have any more{cuisine_text} restaurants to suggest!\n"
            "Try logging some new places or pick a different cuisine."
        )
        return ConversationHandler.END

    restaurant, entries = result
    context.chat_data["suggested_restaurant_id"] = restaurant.id

    # Build suggestion message
    message = f"How about **{restaurant.name}**"
    if restaurant.cuisine:
        message += f" ({restaurant.cuisine})"
    if restaurant.address:
        message += f"\n📍 {restaurant.address}"

    message += "\n\n**Your past visits:**"
    for entry in entries[:3]:
        emoji = _get_sentiment_emoji(entry.sentiment)
        dish = entry.dish or "No dish noted"
        user = entry.user_name or "Someone"
        message += f"\n• {user}: {dish} {emoji}"
        if entry.notes:
            message += f" - {entry.notes}"

    keyboard = [
        [
            InlineKeyboardButton("✅ Let's go!", callback_data=ACCEPT),
            InlineKeyboardButton("🔄 Try another", callback_data=REJECT),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=CANCEL)],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

    return CONFIRMING


async def handle_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Handle accept/reject of restaurant suggestion."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == CANCEL:
        await query.edit_message_text("No problem! Let me know when you're ready to eat.")
        return ConversationHandler.END

    if data == ACCEPT:
        restaurant_id = context.chat_data.get("suggested_restaurant_id")
        db: DatabaseService = context.bot_data["db"]

        # Get restaurant name for the message
        result = await db.get_random_positive_restaurant(cuisine=None, exclude_ids=[])
        # Just use the stored ID to show acceptance
        await query.edit_message_text(
            "Great choice! Enjoy your meal! 🍽️\n\n"
            "Don't forget to log your experience afterwards!"
        )
        return ConversationHandler.END

    if data == REJECT:
        # Add to rejected list
        restaurant_id = context.chat_data.get("suggested_restaurant_id")
        if restaurant_id:
            rejected = context.chat_data.get("rejected_restaurants", [])
            rejected.append(restaurant_id)
            context.chat_data["rejected_restaurants"] = rejected

        return await suggest_restaurant(update, context)

    return CONFIRMING


async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle conversation timeout."""
    # Try to clean up the message if possible
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                "This suggestion has expired. Use /whattoeat to start again!"
            )
        except Exception:
            pass
    return ConversationHandler.END


def _get_sentiment_emoji(sentiment: str) -> str:
    """Get emoji for sentiment."""
    return {
        "positive": "👍",
        "negative": "👎",
        "neutral": "😐",
        "mixed": "🤔",
    }.get(sentiment, "")


def get_what_to_eat_handler() -> ConversationHandler:
    """Create the ConversationHandler for 'what to eat' flow."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("whattoeat", start_what_to_eat),
        ],
        states={
            SELECTING_CUISINE: [
                CallbackQueryHandler(handle_cuisine_selection),
            ],
            CONFIRMING: [
                CallbackQueryHandler(handle_confirmation),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout),
                CallbackQueryHandler(timeout),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
        ],
        conversation_timeout=300,  # 5 minutes
    )


async def trigger_what_to_eat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Trigger what to eat flow from natural language."""
    # Create a fake message to pass to the handler
    await start_what_to_eat(update, context)
