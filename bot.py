import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import fitz  # PyMuPDF
from PIL import Image
import io
import os
from flask import Flask
import threading

# Securely fetch token from Render environment variables
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_data = {}

# --- FLASK WEB SERVER (For Render) ---
@app.route('/')
def home():
    return "Bot is running!"

# --- TELEGRAM BOT LOGIC ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Hello! Send me a PDF file to get started.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if not message.document.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "Please send a valid PDF file.")
        return
    
    bot.send_message(message.chat.id, "Downloading your PDF...")
    
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    pdf_path = f"{message.chat.id}_input.pdf"
    
    with open(pdf_path, 'wb') as new_file:
        new_file.write(downloaded_file)
        
    user_data[message.chat.id] = {'pdf_path': pdf_path}
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("1. Faded Background Image", callback_data="opt_img"))
    markup.add(InlineKeyboardButton("2. Clickable Text Link", callback_data="opt_link"))
    markup.add(InlineKeyboardButton("3. Both (Image + Link)", callback_data="opt_both"))
    
    bot.send_message(message.chat.id, "PDF received! What do you want to add?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('opt_'))
def handle_choice(call):
    chat_id = call.message.chat.id
    choice = call.data
    user_data[chat_id]['choice'] = choice
    
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    
    if choice in ['opt_img', 'opt_both']:
        msg = bot.send_message(chat_id, "Please send the watermark Image (send it as a **Photo**, not a file).", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_image_step)
    else:
        msg = bot.send_message(chat_id, "Please send the Text you want to display for the link.")
        bot.register_next_step_handler(msg, process_link_text_step)

def process_image_step(message):
    chat_id = message.chat.id
    if not message.photo:
        msg = bot.send_message(chat_id, "That doesn't look like an image. Please send a Photo.")
        bot.register_next_step_handler(msg, process_image_step)
        return
        
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    img_path = f"{chat_id}_watermark.png"
    
    with open(img_path, 'wb') as new_file:
        new_file.write(downloaded_file)
        
    user_data[chat_id]['img_path'] = img_path
    
    if user_data[chat_id]['choice'] == 'opt_both':
        msg = bot.send_message(chat_id, "Image saved! Now, send the Text you want to display for the link.")
        bot.register_next_step_handler(msg, process_link_text_step)
    else:
        bot.send_message(chat_id, "Processing your PDF, please wait...")
        process_pdf(chat_id)

def process_link_text_step(message):
    chat_id = message.chat.id
    user_data[chat_id]['link_text'] = message.text
    msg = bot.send_message(chat_id, "Great! Now send the URL (e.g., https://t.me/yourchannel) that the text should link to.")
    bot.register_next_step_handler(msg, process_link_url_step)

def process_link_url_step(message):
    chat_id = message.chat.id
    user_data[chat_id]['link_url'] = message.text
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Header", callback_data="pos_header"),
               InlineKeyboardButton("Footer", callback_data="pos_footer"),
               InlineKeyboardButton("Both", callback_data="pos_both"))
    
    bot.send_message(chat_id, "Where should the link be placed?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pos_'))
def handle_position(call):
    chat_id = call.message.chat.id
    user_data[chat_id]['link_pos'] = call.data
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    bot.send_message(chat_id, "Processing your PDF, please wait...")
    process_pdf(chat_id)

def apply_faded_opacity(image_path, opacity=0.15):
    img = Image.open(image_path).convert("RGBA")
    alpha = img.split()[3]
    alpha = alpha.point(lambda p: p * opacity)
    img.putalpha(alpha)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

def process_pdf(chat_id):
    data = user_data.get(chat_id, {})
    input_pdf = data.get('pdf_path')
    output_pdf = f"{chat_id}_final.pdf"
    
    if not input_pdf:
        bot.send_message(chat_id, "Session expired. Please send the PDF again.")
        return
        
    doc = fitz.open(input_pdf)
    choice = data.get('choice')
    
    img_bytes = None
    if choice in ['opt_img', 'opt_both']:
        img_bytes = apply_faded_opacity(data['img_path'], opacity=0.15) 
        
    for page in doc:
        rect = page.rect
        
        # Insert Faded Background Image
        if img_bytes:
            img_rect = fitz.Rect(rect.width * 0.15, rect.height * 0.25, rect.width * 0.85, rect.height * 0.75)
            page.insert_image(img_rect, stream=img_bytes, keep_proportion=True, overlay=False)
            
        # Insert Clickable Link
        if choice in ['opt_link', 'opt_both']:
            pos = data.get('link_pos')
            text = data.get('link_text')
            url = data.get('link_url')
            
            h_rect = fitz.Rect(0, 20, rect.width, 50)
            f_rect = fitz.Rect(0, rect.height - 50, rect.width, rect.height - 20)
            
            if pos in ['pos_header', 'pos_both']:
                page.insert_textbox(h_rect, text, fontsize=12, color=(0,0,1), align=fitz.TEXT_ALIGN_CENTER)
                page.insert_link({"kind": fitz.LINK_URI, "from": h_rect, "uri": url})
                
            if pos in ['pos_footer', 'pos_both']:
                page.insert_textbox(f_rect, text, fontsize=12, color=(0,0,1), align=fitz.TEXT_ALIGN_CENTER)
                page.insert_link({"kind": fitz.LINK_URI, "from": f_rect, "uri": url})
                
    doc.save(output_pdf)
    doc.close()
    
    with open(output_pdf, 'rb') as pdf_file:
        bot.send_document(chat_id, pdf_file, caption="Done! Here is your branded PDF.")
        
    # Clean up files from server
    try:
        os.remove(input_pdf)
        os.remove(output_pdf)
        if 'img_path' in data: os.remove(data['img_path'])
    except Exception:
        pass
    user_data.pop(chat_id, None)

def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    print("Starting bot thread...")
    threading.Thread(target=run_bot, daemon=True).start()
    
    print("Starting Flask server...")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
