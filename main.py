import asyncio
import os
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import google.generativeai as genai

# PDF yaratish uchun kutubxonalar
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# .env faylini yuklash
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini AI sozlamalari
genai.configure(api_key=GEMINI_API_KEY)

generation_config = genai.GenerationConfig(
    temperature=0.2,
    top_p=0.8,
    top_k=40,
    max_output_tokens=8192
)

model = genai.GenerativeModel(
    model_name='models/gemini-3.8-flash',
    generation_config=generation_config
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Holatlarni aniqlash
class TestGeneratorState(StatesGroup):
    waiting_for_count = State()
    waiting_for_format = State()

# Inline Klaviaturalar (Tugmalar)
def get_count_keyboard(is_photo: bool) -> InlineKeyboardMarkup:
    if is_photo:
        counts = [3, 5, 10]
    else:
        counts = [5, 10, 20, 30, 50]
    
    buttons = [[InlineKeyboardButton(text=f"📝 {c} ta test", callback_data=f"count_{c}")] for c in counts]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_format_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📄 Matn ko'rinishida", callback_data="format_1")],
        [InlineKeyboardButton(text="📥 PDF fayl ko'rinishida", callback_data="format_2")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# PDF yaratuvchi yordamchi funksiya
def create_pdf(text: str) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    style_normal = ParagraphStyle(
        'CustomStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        spaceAfter=6
    )
    
    text = text.replace('ʻ', "'").replace('`', "'").replace('’', "'").replace('‘', "'")
    
    story = []
    lines = text.split('\n')
    for line in lines:
        clean_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if clean_line.strip():
            story.append(Paragraph(clean_line, style_normal))
        else:
            story.append(Spacer(1, 4))
            
    doc.build(story)
    buffer.seek(0)
    return buffer

# /start buyrug'i
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Xush kelibsiz! Men kitob, hujjatlar va rasmlardan test tuzuvchi botman.\n\n"
        "Menga:\n"
        "Matn yozilgan rasm yokida \n"
        "elektron kitob (PDF/TXT fayl) yuboring.\n"
        "Men sizga test tuzib beraman."
    )

# 1. Rasm qabul qilinganda
@dp.message(F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    await state.update_data(
        file_bytes=downloaded_file.read(),
        mime_type="image/jpeg",
        is_photo=True
    )
    await state.set_state(TestGeneratorState.waiting_for_count)
    await message.answer(
        "📷 Rasm qabul qilindi!\n\nNechta test tuzilsin? Quyidagi tugmalardan birini tanlang:",
        reply_markup=get_count_keyboard(is_photo=True)
    )

# 2. Hujjat qabul qilinganda
@dp.message(F.document)
async def process_document(message: types.Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.endswith(('.pdf', '.txt')):
        await message.answer("⚠️ Iltimos, faqat PDF yoki TXT formatidagi fayl yuboring.")
        return

    file_info = await bot.get_file(doc.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    mime_type = "application/pdf" if doc.file_name.endswith('.pdf') else "text/plain"
    
    await state.update_data(
        file_bytes=downloaded_file.read(),
        mime_type=mime_type,
        is_photo=False
    )
    await state.set_state(TestGeneratorState.waiting_for_count)
    await message.answer(
        "📁 Hujjat qabul qilindi!\n\nNechta test tuzilsin? Quyidagi tugmalardan birini tanlang:",
        reply_markup=get_count_keyboard(is_photo=False)
    )

# 3. Tugma orqali test soni tanlanganda
@dp.callback_query(TestGeneratorState.waiting_for_count, F.data.startswith("count_"))
async def process_count_callback(callback: types.CallbackQuery, state: FSMContext):
    count = int(callback.data.split("_")[1])
    await state.update_data(test_count=count)
    await state.set_state(TestGeneratorState.waiting_for_format)
    
    await callback.message.edit_text(
        f"✅ **{count} ta** test tanlandi.\n\nTest qaysi formatda taqdim etilsin?",
        reply_markup=get_format_keyboard()
    )
    await callback.answer()

# 4. Tugma orqali format tanlanganda va test tayyorlanganda
@dp.callback_query(TestGeneratorState.waiting_for_format, F.data.startswith("format_"))
async def generate_tests_callback(callback: types.CallbackQuery, state: FSMContext):
    choice = callback.data.split("_")[1]
    data = await state.get_data()
    count = data.get("test_count")
    is_photo = data.get("is_photo")

    format_name = "Matn" if choice == '1' else "PDF fayl"
    
    await callback.message.edit_text(f"⏳ **{count} ta** test {format_name} ko'rinishida tuzilmoqda, biroz kuting...")
    await bot.send_chat_action(chat_id=callback.message.chat.id, action="typing")

    file_parts = [{"mime_type": data["mime_type"], "data": data["file_bytes"]}]
    
    format_instruction = (
        f"MUHIM TASHKILIY QOIDA:\n"
        f"Siz ROSTDA HAM to'liq **{count} ta** savol tuzishingiz SHART! Jarayonni yarim yo'lda to'xtatmang.\n"
        f"1-savoldan to {count}-savolgacha birin-ketin raqamlab barcha {count} ta savolni variantlari bilan yozing.\n\n"
        "MATEMATIK FORMULALAR QOIDASI:\n"
        "1. UMUMan '_', '^', '{}', '\\', '$' LaTeX simvollaridan foydalanmang!\n"
        "2. Indekslarni oddiy yozing (masalan: aik, x²).\n\n"
        "TEST FORMATI QOIDASI:\n"
        "Savollar ostida javobni ko'rsatmang! Avval barcha savollarni (A, B, C, D variantlari bilan) chiqaring.\n"
        "Barcha savollar tugagach, eng pastda alohida qilib to'g'ri javoblar kalitini keltiring.\n"
        "Namuna:\n"
        "1. Savol matni...\nA) ...\nB) ...\nC) ...\nD) ...\n\n"
        "2. Savol matni...\n...\n\n"
        "--- TO'G'RI JAVOBLAR KALITI ---\n"
        "1-A, 2-C, 3-B ..."
    )

    prompt = (
        f"Matndan foydalanib, ROSTAKAMiga **{count} ta** 4 ta variantli (A, B, C, D) test tuzing.\n\n"
        f"{format_instruction}"
    )

    try:
        response = model.generate_content([prompt, file_parts[0]])
        result_text = response.text

        if choice == '1':
            await callback.message.delete()
            if len(result_text) > 4000:
                for x in range(0, len(result_text), 4000):
                    await callback.message.answer(result_text[x:x+4000])
            else:
                await callback.message.answer(result_text)
        elif choice == '2':
            await callback.message.delete()
            pdf_buffer = create_pdf(result_text)
            pdf_file = BufferedInputFile(pdf_buffer.read(), filename=f"{count}_ta_test.pdf")
            await callback.message.answer_document(
                document=pdf_file,
                caption=f"✨ Siz so'ragan {count} ta test PDF fayl shaklida tayyorlandi!"
            )
            
    except Exception as e:
        error_text = str(e)
        if "429" in error_text or "Quota exceeded" in error_text:
            await callback.message.answer("⚠️ Xatolik yuz berganga o'xshaydi, iltimos birozdan song urinib koring.")
        else:
            await callback.message.answer(f"Xatolik yuz berdi: {e}")
    
    await callback.answer()
    await state.clear()

# Botni ishga tushirish
async def main():
    print("Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())