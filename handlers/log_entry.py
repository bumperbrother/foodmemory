"""Handler for logging food entries."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

from services.llm import ParsedLogEntry, ParsedDetails
from services.database import DatabaseService
from services.places import PlacesService

logger = logging.getLogger(__name__)

# Conversation states for exact order flow
WAITING_FOR_ORDER = 0

# Callback data
ADD_ORDER_YES = "add_order_yes"
ADD_ORDER_NO = "add_order_no"


async def handle_log_entry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed: ParsedLogEntry,
) -> None:
    """Handle a new food entry log.

    Args:
        update: Telegram update
        context: Bot context with services
        parsed: Parsed log entry from LLM
    """
    db: DatabaseService = context.bot_data["db"]
    places: PlacesService = context.bot_data["places"]

    user = update.effective_user
    user_name = user.first_name if user else "Unknown"
    user_telegram_id = user.id if user else None

    # Try to find or create restaurant with enrichment
    restaurant = await db.find_restaurant_by_name(parsed.restaurant_name)

    if not restaurant:
        # Try to enrich with Google Places
        place_data = await places.search_restaurant(parsed.restaurant_name)

        if place_data:
            restaurant = await db.find_or_create_restaurant(
                name=parsed.restaurant_name,
                google_place_id=place_data.place_id,
                address=place_data.address,
                latitude=place_data.latitude,
                longitude=place_data.longitude,
                cuisine=place_data.cuisine,
                price_level=place_data.price_level,
                dine_in=place_data.dine_in,
                takeout=place_data.takeout,
                delivery=place_data.delivery,
            )
        else:
            # Create without enrichment
            restaurant = await db.find_or_create_restaurant(name=parsed.restaurant_name)
    else:
        # Existing restaurant - try to enrich if missing place_id
        if not restaurant.google_place_id:
            place_data = await places.search_restaurant(parsed.restaurant_name)
            if place_data:
                restaurant = await db.find_or_create_restaurant(
                    name=restaurant.name,
                    google_place_id=place_data.place_id,
                    address=place_data.address,
                    latitude=place_data.latitude,
                    longitude=place_data.longitude,
                    cuisine=place_data.cuisine,
                    price_level=place_data.price_level,
                    dine_in=place_data.dine_in,
                    takeout=place_data.takeout,
                    delivery=place_data.delivery,
                )

    # Create the entry
    entry = await db.add_entry(
        restaurant_id=restaurant.id,
        user_name=user_name,
        user_telegram_id=user_telegram_id,
        dish=parsed.dish_name,
        notes=parsed.notes,
        sentiment=parsed.sentiment,
        sentiment_score=parsed.sentiment_score,
        tags=parsed.tags,
    )

    # Store last entry in chat data for follow-up
    context.chat_data["last_entry_id"] = entry.id
    context.chat_data["last_entry_restaurant"] = restaurant.name

    # Build confirmation message
    dish_part = f" {parsed.dish_name}" if parsed.dish_name else ""
    sentiment_emoji = _get_sentiment_emoji(parsed.sentiment)

    message = f"Got it, {user_name}!{dish_part} at {restaurant.name} {sentiment_emoji}"

    if restaurant.cuisine:
        message += f" ({restaurant.cuisine})"

    if parsed.tags:
        message += f"\nTags: {', '.join(parsed.tags)}"

    # Add follow-up question with buttons
    message += "\n\nWant to save a specific order for next time?"

    keyboard = [
        [
            InlineKeyboardButton("Yes", callback_data=ADD_ORDER_YES),
            InlineKeyboardButton("No thanks", callback_data=ADD_ORDER_NO),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(message, reply_markup=reply_markup)


async def handle_order_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Handle the yes/no callback for adding an order."""
    query = update.callback_query
    await query.answer()

    if query.data == ADD_ORDER_NO:
        await query.edit_message_reply_markup(reply_markup=None)
        return ConversationHandler.END

    if query.data == ADD_ORDER_YES:
        last_restaurant = context.chat_data.get("last_entry_restaurant", "this place")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"What's your go-to order at {last_restaurant}? "
            "(e.g., \"Pad Thai, medium spicy, no peanuts\")"
        )
        return WAITING_FOR_ORDER

    return ConversationHandler.END


async def handle_exact_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Handle the exact order text input."""
    db: DatabaseService = context.bot_data["db"]

    last_entry_id = context.chat_data.get("last_entry_id")
    last_restaurant = context.chat_data.get("last_entry_restaurant")

    if not last_entry_id:
        await update.message.reply_text("Sorry, I lost track of which entry to update. Try logging again!")
        return ConversationHandler.END

    exact_order = update.message.text

    # Update the entry with the exact order
    await db.update_entry(last_entry_id, exact_order=exact_order)

    await update.message.reply_text(
        f"Saved your order at {last_restaurant}: \"{exact_order}\"\n"
        "I'll remind you of this next time!"
    )

    return ConversationHandler.END


async def handle_order_timeout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Handle conversation timeout."""
    return ConversationHandler.END


def get_order_conversation_handler() -> ConversationHandler:
    """Create the ConversationHandler for exact order flow."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_order_callback, pattern=f"^({ADD_ORDER_YES}|{ADD_ORDER_NO})$"),
        ],
        states={
            WAITING_FOR_ORDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exact_order),
            ],
        },
        fallbacks=[],
        conversation_timeout=120,  # 2 minutes
        per_message=False,
    )


async def handle_add_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed: ParsedDetails,
) -> str:
    """Handle adding details to a previous entry.

    Args:
        update: Telegram update
        context: Bot context with services
        parsed: Parsed details from LLM

    Returns:
        Confirmation message to send
    """
    db: DatabaseService = context.bot_data["db"]

    last_entry_id = context.chat_data.get("last_entry_id")
    last_restaurant = context.chat_data.get("last_entry_restaurant")

    if not last_entry_id:
        # Check if they mentioned a restaurant - if so, give helpful guidance
        if parsed.restaurant_name:
            return (
                f"I don't have a recent entry to add to. "
                f"To log something at {parsed.restaurant_name}, try:\n"
                f"\"[dish] at {parsed.restaurant_name}, [how was it]\""
            )
        return "I don't have a recent entry to add details to. Try logging a new experience first!"

    # Check if user mentioned a different restaurant
    if parsed.restaurant_name:
        # Fuzzy match - check if the names are similar
        mentioned = parsed.restaurant_name.lower().strip()
        last = (last_restaurant or "").lower().strip()
        if mentioned not in last and last not in mentioned:
            return (
                f"Your last entry was at {last_restaurant}, not {parsed.restaurant_name}.\n\n"
                f"To add something to {parsed.restaurant_name}, try:\n"
                f"\"[dish] at {parsed.restaurant_name}, [how was it]\"\n\n"
                f"Or to see what you've had there: \"What have we had at {parsed.restaurant_name}?\""
            )

    # Get the current entry
    entry = await db.get_entry(last_entry_id)
    if not entry:
        return "I couldn't find that entry anymore. Try logging a new experience!"

    # Build update fields
    updates = {}

    if parsed.dish_name:
        # Append to existing dish or set new
        if entry.dish:
            updates["dish"] = f"{entry.dish}, {parsed.dish_name}"
        else:
            updates["dish"] = parsed.dish_name

    if parsed.notes:
        # Append to existing notes
        if entry.notes:
            updates["notes"] = f"{entry.notes}. {parsed.notes}"
        else:
            updates["notes"] = parsed.notes

    if parsed.sentiment:
        updates["sentiment"] = parsed.sentiment

    if parsed.sentiment_score is not None:
        updates["sentiment_score"] = parsed.sentiment_score

    if parsed.tags:
        # Merge tags
        existing_tags = entry.tags or []
        updates["tags"] = list(set(existing_tags + parsed.tags))

    if updates:
        await db.update_entry(last_entry_id, **updates)

    # Build response
    parts = []
    if parsed.dish_name:
        parts.append(f"added {parsed.dish_name}")
    if parsed.notes:
        parts.append(f"noted: {parsed.notes}")
    if parsed.tags:
        parts.append(f"tagged: {', '.join(parsed.tags)}")

    if parts:
        return f"Updated your {last_restaurant} entry: {', '.join(parts)}"
    else:
        return f"Got it! (though I'm not sure what to add to your {last_restaurant} entry)"


def _get_sentiment_emoji(sentiment: str) -> str:
    """Get emoji for sentiment."""
    return {
        "positive": "👍",
        "negative": "👎",
        "neutral": "😐",
        "mixed": "🤔",
    }.get(sentiment, "")
