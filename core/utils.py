import asyncio

async def delete_later(bot_instance, chat_id: int, message_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await bot_instance.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass
