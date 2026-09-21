from aiogram import Router
from aiogram.types import InlineQuery,InlineQueryResultArticle,InlineQueryResultsButton,InputTextMessageContent
from data_manager import data_manager,ScheduleUnavailable,UnknownGroup,UNAVAILABLE
from calendar_helpers import prepare_inline
inline_router=Router(name='inline')

@inline_router.inline_query()
async def inline_query_handler(query:InlineQuery):
    group=data_manager.get_user_group(query.from_user.id)
    if not group:
        await query.answer([],button=InlineQueryResultsButton(text='Сначала выберите группу',start_parameter='select_group'),cache_time=1,is_personal=True)
        return
    try:
        result_id,title,text=prepare_inline(data_manager,query.from_user.id,group,query.query)
    except UnknownGroup:
        await query.answer([],button=InlineQueryResultsButton(text='Выберите группу заново',start_parameter='select_group'),cache_time=1,is_personal=True)
        return
    except ScheduleUnavailable:
        result_id,title,text='unavailable','Расписание недоступно',UNAVAILABLE
    article=InlineQueryResultArticle(id=result_id,title=title,description='Группа: '+group,input_message_content=InputTextMessageContent(message_text=text,parse_mode='HTML'))
    await query.answer([article],cache_time=5,is_personal=True)
