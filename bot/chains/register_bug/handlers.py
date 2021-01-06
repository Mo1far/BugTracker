import os

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import User as TgUser

from bot.chains.base.kb import start_kb
from bot.chains.register_bug.kb import cancel_kb, get_admin_decision_kb
from bot.chains.register_bug.state import RegisterBug
from bot.config import ADMIN_CHAT_ID
from bot.core import dp, bot
from db.config import UPLOAD_DIR
from db.models.bug import Bug, BugStatus


@dp.callback_query_handler(lambda x: x.data == 'bug_register_cancel', state='*')
async def cancel(c: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await bot.send_message(c.from_user.id, 'Скасовано', reply_markup=start_kb)
    await c.answer('Скасовано')


@dp.message_handler(regexp='Додати баг 🐞', state='*')
async def add_bug_start(msg: types.Message):
    await RegisterBug.wait_photo.set()
    await msg.answer('Надішліть фото багу 📸', reply_markup=cancel_kb)


@dp.message_handler(state=RegisterBug.wait_photo, content_types=['photo', 'video', 'document'])
async def add_bug_photo(msg: types.Message, state: FSMContext):
    if len(msg.photo) == 0:
        await msg.answer('Упсс.. Помилка 😔\n'
                         'Спробуйте надіслати фото, або скасуйте додавання багу', reply_markup=cancel_kb)

    await state.set_data({'photo_id': msg.photo[-1].file_id})
    await RegisterBug.wait_description.set()
    await msg.answer('Опишіть проблему в 1 повідомленні', reply_markup=cancel_kb)


@dp.message_handler(state=RegisterBug.wait_description)
async def add_bug_description(msg: types.Message, state: FSMContext):
    await state.update_data({'description': msg.text})
    await RegisterBug.wait_location.set()
    await msg.answer('Надішліть місцезнаходження (аудиторію, корпус) якомога конкретніше 🏢', reply_markup=cancel_kb)


@dp.message_handler(state=RegisterBug.wait_location)
async def add_bug_location(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    default_status = await BugStatus.select('id').where(BugStatus.status == 'pending').gino.scalar()

    bug = await Bug.create(photo_path=data.get('photo_id'),
                           description=data.get('description'),
                           location=msg.text,
                           status=default_status,
                           user=TgUser.get_current())
    await bot.download_file(data.get('photo_id'), os.path.join(UPLOAD_DIR, f'{bug.id}.jpg'))
    await bug.update(photo_path=f'uploads/bugs/{bug.id}.jpg').apply()

    await bot.send_photo(ADMIN_CHAT_ID, data.get('photo_id'), caption=f'Баг # {bug.id}\n'
                                                                      f'Місцезнаходження <i>{msg.text}</i>\n'
                                                                      f'Опис <i>{data.get("description")}</i>',
                         reply_markup=get_admin_decision_kb(bug.id))

    await state.finish()
    await msg.answer(f'Баг № {bug.id} було надіслано адмінам. '
                     f'Найближчим часом інформацію перевірять, та сповістять вас\n\n'
                     f'Дякуємо за повідомлення 😊')


@dp.callback_query_handler(lambda x: x.data.startswith('admin_decision_'))
async def admin_decision_(cq: types.CallbackQuery):
    await cq.message.delete_reply_markup()

    c_data = cq.data.replace('admin_decision_', '')
    decision, bug_id = c_data.split('_')

    bug = await Bug.get(int(bug_id))
    status = await BugStatus.select('id').where(BugStatus.status == decision).gino.scalar()

    if decision == 'registered':
        await bot.send_message(bug.user, f'Баг № {bug.id} '
                                         f'прийнято в роботу, будемо старатися пофіксити його найближчим часом 😉')
    else:
        await bot.send_message(bug.user, f'Мабуть ти помилився при описі багу № {bug.id} 😔\n\n'
                                         'Наразі відхиляємо твоє повідомлення, '
                                         'але ти можеш додати трішки кращий опис та спробувати ще раз 😉')

    await bug.update(status=status).apply()

    await cq.answer('Готово')
