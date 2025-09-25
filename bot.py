import os
import logging
import re
import threading
import time
import sys
from typing import List, Dict, Any
from dotenv import load_dotenv
import telebot
from telebot import types

# Reduce TeleBot logging for timeout errors
telebot_logger = logging.getLogger('TeleBot')
telebot_logger.setLevel(logging.WARNING)  # Only show WARNING and ERROR, not INFO
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from database import DatabaseManager
from translation_manager import TranslationManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AffiliateAPI:
    def __init__(self):
        self.license_code = os.getenv('LICENSE_CODE')
        self.email = os.getenv('DOUBLEGRAM_EMAIL')
        self.api_url = 'https://affiliate.doublegram.com'
        self.product_code = 'DGAFF'
        
    def validate_license(self):
        """Valida la licenza all'avvio del bot"""
        try:
            response = requests.get(
                f"{self.api_url}/api/validate",
                headers={
                    'license-key': self.license_code,
                    'email': self.email,
                    'product-code': self.product_code
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ License is valid")
                print(f"📋 Database: {data['database']}")
                print(f"👤 User ID: {data['user_id']}")
                return True
            else:
                print(f"❌ License is not valid: {response.json()}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Connection error to API: {e}")
            return False

class AmazonBot:
    def __init__(self):
        # Validazione licenza prima di tutto
        logger.info("🔐 License validation in progress...")
        affiliate_api = AffiliateAPI()
        
        if not affiliate_api.validate_license():
            logger.error("❌ License is not valid. Bot not started.")
            sys.exit(1)
        
        logger.info("✅ License validated successfully!")
        
        # Carica configurazioni
        self.bot_token = os.getenv('BOT_TOKEN')
        self.welcome_message = os.getenv('WELCOME_MESSAGE', 'Benvenuto! Come posso aiutarti?')
        
        # Parse authorized users
        authorized_users_str = os.getenv('AUTHORIZED_USERS', '')
        self.authorized_users = []
        if authorized_users_str:
            try:
                self.authorized_users = [int(user_id.strip()) for user_id in authorized_users_str.split(',') if user_id.strip()]
            except ValueError:
                logger.error("Error parsing authorized users from .env file")
        
        if not self.bot_token:
            raise ValueError("BOT_TOKEN not found in .env file")
        
        # Inizializza bot e database
        self.bot = telebot.TeleBot(self.bot_token)
        self.db = DatabaseManager("dummy") 
        
        # Inizializza il sistema di traduzioni
        self.translator = TranslationManager()
        
        # Inizializza configurazioni di default nel database remoto
        self.initialize_default_configurations()
        
        # Configurazione OpenAI
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        
        # Dizionario per tracciare gli stati degli utenti durante l'inserimento categorie
        self.user_states: Dict[int, Dict[str, Any]] = {}
        
        # Thread per il cronjob di controllo prezzi
        self.cronjob_thread = None
        self.cronjob_running = False
        
        # User agent per web scraping
        self.user_agent = UserAgent()
        
        # Registra i handlers
        self.register_handlers()
        
        logger.info(f"Bot initialized with {len(self.authorized_users)} authorized users")
    
    def is_user_authorized(self, user_id: int) -> bool:
        """Verifica se l'utente è autorizzato ad utilizzare il bot (God Admin o Regular Admin)"""
        # Controlla prima se è un God Admin (definito nel .env)
        if user_id in self.authorized_users:
            return True
        
        # Altrimenti controlla se è un Regular Admin aggiunto al database
        return self.db.is_admin_user(user_id)
    
    def is_god_admin(self, user_id: int) -> bool:
        """Verifica se l'utente è un God Admin (definito nel .env)"""
        return user_id in self.authorized_users
    
    def get_text(self, key: str, **kwargs) -> str:
        """Helper method per ottenere testi tradotti"""
        return self.translator.get_text(key, **kwargs)
    
    def escape_markdown(self, text: str) -> str:
        """Escape caratteri speciali per Markdown V2"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f'\\{char}')
        return escaped_text
    
    def escape_html(self, text: str) -> str:
        """Escape caratteri speciali per HTML"""
        if not text:
            return ""
        return (text.replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;')
                    .replace("'", '&#x27;'))
    
    def convert_channel_link_to_chat_id(self, channel_link: str) -> str:
        """Converte un link del canale nel formato corretto per l'API Telegram"""
        # Se è già un chat ID numerico (inizia con -), restituiscilo così com'è
        if channel_link.startswith('-') and channel_link[1:].isdigit():
            return channel_link
        
        # Se è un link t.me, estrae il nome del canale
        if 't.me/' in channel_link:
            # Estrae la parte dopo t.me/
            channel_name = channel_link.split('t.me/')[-1]
            # Rimuove eventuali parametri URL
            channel_name = channel_name.split('?')[0].split('#')[0]
            # Aggiunge @ se non c'è già
            if not channel_name.startswith('@'):
                channel_name = f'@{channel_name}'
            return channel_name
        
        # Se inizia già con @, restituiscilo così com'è
        if channel_link.startswith('@'):
            return channel_link
        
        # Altrimenti, assumiamo sia un nome canale e aggiungiamo @
        return f'@{channel_link}'
    
    def register_handlers(self):
        """Registra tutti gli handlers del bot"""
        logger.info("🔧 Registration of handlers in progress...")
        
        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            user_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name
            last_name = message.from_user.last_name
            
            logger.info(f"Command /start received from {user_id} (@{username})")
            
            # Verifica autorizzazione
            if not self.is_user_authorized(user_id):
                self.bot.reply_to(
                    message, 
                    self.get_text('spiacente_non_autorizzato')
                )
                logger.warning(f"Access denied for unauthorized user: {user_id} (@{username})")
                return
            
            # Aggiungi/aggiorna utente nel database
            self.db.add_user(user_id, username, first_name, last_name)
            self.db.log_interaction(user_id, '/start', 'Comando start eseguito')
            
            # Invia messaggio di benvenuto con menu principale
            welcome_text = f"{self.get_text('welcome_greeting', name=first_name)}\n\n"
            welcome_text += f"{self.get_text('welcome_doublegram')}\n\n"
            welcome_text += f"{self.get_text('welcome_ready')}\n\n"
            welcome_text += f"{self.get_text('welcome_docs')}\n\n"
            welcome_text += f"{self.get_text('welcome_news')}\n\n"
            
            # Crea keyboard con i bottoni (stesso del /help)
            keyboard = types.InlineKeyboardMarkup()
            
            # Riga 1: Categorie + Link Categorie (stesso row)
            categories_btn = types.InlineKeyboardButton(self.get_text('categories'), callback_data="show_categories")
            link_categories_btn = types.InlineKeyboardButton(self.get_text('link_categories'), callback_data="show_link_categories")
            keyboard.row(categories_btn, link_categories_btn)
            
            # Riga 2: Prodotti (da solo)
            products_btn = types.InlineKeyboardButton(self.get_text('products'), callback_data="show_products_menu")
            keyboard.add(products_btn)
            
            # Riga 3: Cronjob (da solo) 
            cronjob_btn = types.InlineKeyboardButton(self.get_text('cronjob'), callback_data="show_cronjob_menu")
            keyboard.add(cronjob_btn)
            
            # Riga 4: Canale Database (da solo)
            channel_btn = types.InlineKeyboardButton(self.get_text('channel_db'), callback_data="show_channel_config")
            keyboard.add(channel_btn)
            
            # Riga 5: Approvazione Automatica (da solo)
            auto_approval_btn = types.InlineKeyboardButton(self.get_text('auto_approval'), callback_data="show_auto_approval_config")
            keyboard.add(auto_approval_btn)
            
            # Riga 6: Prompt AI (da solo)
            prompt_btn = types.InlineKeyboardButton(self.get_text('prompt_ai'), callback_data="show_prompt_config")
            keyboard.add(prompt_btn)
            
            # Riga 7: Pulsante di acquisto (da solo)
            purchase_btn = types.InlineKeyboardButton(self.get_text('purchase_button'), callback_data="show_purchase_button_config")
            keyboard.add(purchase_btn)
            
            # Riga 8: Slug Amazon (da solo)
            amazon_btn = types.InlineKeyboardButton(self.get_text('slug_amazon'), callback_data="show_amazon_config")
            keyboard.add(amazon_btn)
            
            # Riga 9: Gestione Admin (da solo)
            admin_btn = types.InlineKeyboardButton(self.get_text('admin_management'), callback_data="show_admin_management")
            keyboard.add(admin_btn)
            
            # Riga 10: Impostazioni Lingua (da solo)
            language_btn = types.InlineKeyboardButton(self.get_text('language_settings'), callback_data="language_settings")
            keyboard.add(language_btn)
            
            self.bot.reply_to(message, welcome_text, parse_mode='HTML', reply_markup=keyboard, disable_web_page_preview=True)
            logger.info(f"Welcome message sent to {user_id} (@{username})")
        
        @self.bot.message_handler(commands=['help'])
        def handle_help(message):
            user_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name
            last_name = message.from_user.last_name
            
            if not self.is_user_authorized(user_id):
                self.bot.reply_to(message, self.get_text('spiacente_non_autorizzato'))
                return
            
            self.db.update_user_activity(user_id)
            self.db.log_interaction(user_id, '/help', 'Richiesta help')
            
            # Stesso testo del comando /start
            help_text = f"{self.get_text('welcome_greeting', name=first_name)}\n\n"
            help_text += f"{self.get_text('welcome_doublegram')}\n\n"
            help_text += f"{self.get_text('welcome_ready')}\n\n"
            help_text += f"{self.get_text('welcome_docs')}\n\n"
            help_text += f"{self.get_text('welcome_news')}\n\n"
            
            # Crea keyboard con i bottoni richiesti
            keyboard = types.InlineKeyboardMarkup()
            
            # Riga 1: Categorie + Link Categorie (stesso row)
            categories_btn = types.InlineKeyboardButton(self.get_text('categories'), callback_data="show_categories")
            link_categories_btn = types.InlineKeyboardButton(self.get_text('link_categories'), callback_data="show_link_categories")
            keyboard.row(categories_btn, link_categories_btn)
            
            # Riga 2: Prodotti (da solo)
            products_btn = types.InlineKeyboardButton(self.get_text('products'), callback_data="show_products_menu")
            keyboard.add(products_btn)
            
            # Riga 3: Cronjob (da solo) 
            cronjob_btn = types.InlineKeyboardButton(self.get_text('cronjob'), callback_data="show_cronjob_menu")
            keyboard.add(cronjob_btn)
            
            # Riga 4: Canale Database (da solo)
            channel_btn = types.InlineKeyboardButton(self.get_text('channel_db'), callback_data="show_channel_config")
            keyboard.add(channel_btn)
            
            # Riga 5: Approvazione Automatica (da solo)
            auto_approval_btn = types.InlineKeyboardButton(self.get_text('auto_approval'), callback_data="show_auto_approval_config")
            keyboard.add(auto_approval_btn)
            
            # Riga 6: Prompt AI (da solo)
            prompt_btn = types.InlineKeyboardButton(self.get_text('prompt_ai'), callback_data="show_prompt_config")
            keyboard.add(prompt_btn)
            
            # Riga 7: Pulsante di acquisto (da solo)
            purchase_btn = types.InlineKeyboardButton(self.get_text('purchase_button'), callback_data="show_purchase_button_config")
            keyboard.add(purchase_btn)
            
            # Riga 8: Slug Amazon (da solo)
            amazon_btn = types.InlineKeyboardButton(self.get_text('slug_amazon'), callback_data="show_amazon_config")
            keyboard.add(amazon_btn)
            
            # Riga 9: Gestione Admin (da solo)
            admin_btn = types.InlineKeyboardButton(self.get_text('admin_management'), callback_data="show_admin_management")
            keyboard.add(admin_btn)
            
            # Riga 10: Impostazioni Lingua (da solo)
            language_btn = types.InlineKeyboardButton(self.get_text('language_settings'), callback_data="language_settings")
            keyboard.add(language_btn)
            
            self.bot.reply_to(message, help_text, parse_mode='HTML', reply_markup=keyboard, disable_web_page_preview=True)
        
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback_query(call):
            user_id = call.from_user.id
            
            if not self.is_user_authorized(user_id):
                self.bot.answer_callback_query(call.id, self.get_text('spiacente_non_autorizzato'))
                return
            
            self.db.update_user_activity(user_id)
            
            try:
                if call.data.startswith('add_category'):
                    self.start_add_category_process(call)
                    
                elif call.data.startswith('delete_category_'):
                    category_id = int(call.data.split('_')[2])
                    self.delete_category_confirm(call, category_id)
                    
                elif call.data.startswith('confirm_delete_product_'):
                    # Elimina definitivamente il prodotto (più specifico)
                    product_id = int(call.data.split('_')[3])
                    self.delete_product_final(call, product_id)
                    
                elif call.data.startswith('confirm_delete_'):
                    # Elimina categoria (meno specifico)
                    category_id = int(call.data.split('_')[2])
                    self.delete_category_final(call, category_id)
                    
                elif call.data == 'cancel_delete':
                    self.bot.answer_callback_query(call.id, "❌ " + self.get_text('eliminazione_annullata'))
                    self.show_categories_menu_edit(call)
                
                elif call.data == 'cancel_add_category':
                    self.cancel_add_category_process(call)
                
                elif call.data.startswith('assign_category_'):
                    # Gestisce l'assegnazione di un prodotto a una categoria
                    parts = call.data.split('_')
                    product_id = int(parts[2])
                    category_id = int(parts[3])
                    self.assign_product_to_category(call, product_id, category_id)
                
                elif call.data.startswith('link_category_'):
                    # Gestisce la selezione di categoria per assegnazione link Telegram
                    category_id = int(call.data.split('_')[2])
                    self.start_telegram_link_process(call, category_id)
                
                elif call.data == 'cronjob_configure':
                    # Inizia configurazione cronjob
                    self.start_cronjob_configuration(call)
                
                elif call.data == 'cronjob_toggle':
                    # Attiva/disattiva cronjob
                    self.toggle_cronjob(call)
                
                elif call.data == 'cronjob_status':
                    # Mostra status cronjob
                    self.show_cronjob_status(call)
                
                elif call.data.startswith('approve_'):
                    # Gestisce l'approvazione di un prodotto
                    approval_data = call.data[8:]  # Rimuove "approve_"
                    self.approve_discount_notification(call, approval_data)
                
                elif call.data == 'add_new_product':
                    # Inizia processo aggiunta prodotto
                    self.start_add_product_process_edit(call, user_id)
                
                elif call.data == 'back_to_products_menu':
                    # Torna al menu principale prodotti
                    self.show_products_categories_menu_edit(call)
                
                elif call.data == 'back_to_main_menu':
                    # Torna al menu principale (/help)
                    self.show_help_menu_edit(call)
                
                elif call.data == 'language_settings':
                    # Mostra impostazioni lingua
                    self.show_language_settings(call)
                
                elif call.data.startswith('set_language_'):
                    # Imposta una nuova lingua
                    language = call.data[13:]  # Rimuove "set_language_"
                    self.set_language(call, language)
                
                elif call.data == 'show_categories':
                    # Mostra menu categorie
                    self.show_categories_menu_edit(call)
                
                elif call.data == 'show_link_categories':
                    # Mostra menu link categorie
                    self.show_categories_for_telegram_link_edit(call)
                
                elif call.data == 'show_cronjob_menu':
                    # Controlla prima se c'è un canale database configurato
                    self.check_channel_before_cronjob(call)
                
                elif call.data == 'show_products_menu':
                    # Mostra menu prodotti
                    self.show_products_categories_menu_edit(call)
                
                elif call.data == 'show_channel_config':
                    # Mostra configurazione canale database
                    self.show_channel_config_edit(call)
                
                elif call.data == 'show_prompt_config':
                    # Mostra configurazione prompt AI
                    self.show_prompt_config_edit(call)
                
                elif call.data == 'show_amazon_config':
                    # Mostra configurazione slug Amazon
                    self.show_amazon_config_edit(call)
                
                elif call.data == 'show_auto_approval_config':
                    # Mostra configurazione approvazione automatica
                    self.show_auto_approval_config_edit(call)
                
                elif call.data == 'show_admin_management':
                    # Mostra gestione admin
                    self.show_admin_management_edit(call)
                
                elif call.data.startswith('view_category_products_'):
                    # Visualizza prodotti di una categoria con paginazione (DEVE ESSERE PRIMA di view_category_)
                    logger.info(f"Managing callback view_category_products_: {call.data}")
                    parts = call.data.split('_')
                    logger.info(f"Parts: {parts}")
                    if len(parts) >= 5:
                        try:
                            category_id = int(parts[3])
                            page = int(parts[4])
                            self.show_category_products(call.message.chat.id, category_id, page, call.message.message_id)
                            category = self.db.get_category_by_id(category_id)
                            category_name = category[1] if category else "Categoria"
                            self.bot.answer_callback_query(call.id, f"📂 {category_name} - " + self.get_text('pagina') + " " + str(page + 1))
                        except (ValueError, IndexError) as e:
                            logger.error(f"Error parsing callback view_category_products_: {e}")
                            self.bot.answer_callback_query(call.id, self.get_text('errore_caricamento_prodotti'))
                    else:
                        logger.error(f"Invalid format for callback view_category_products_: {call.data}")
                        self.bot.answer_callback_query(call.id, self.get_text('formato_callback_non_valido'))
                
                elif call.data.startswith('view_category_'):
                    # Mostra dettagli di una categoria
                    logger.info(f"Managing callback view_category_: {call.data}")
                    parts = call.data.split('_')
                    logger.info(f"Parts per view_category: {parts}")
                    if len(parts) >= 3:
                        try:
                            category_id = int(parts[2])
                            self.show_category_details(call, category_id)
                        except ValueError as e:
                            logger.error(f"Error parsing callback view_category_: {e}")
                            self.bot.answer_callback_query(call.id, self.get_text('errore_caricamento_categoria'))
                    else:
                        logger.error(f"Invalid format for callback view_category_: {call.data}")
                        self.bot.answer_callback_query(call.id, self.get_text('formato_callback_non_valido'))
                
                elif call.data == 'start_channel_config':
                    # Inizia configurazione canale
                    self.start_channel_configuration_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_canale'))
                
                elif call.data == 'start_prompt_config':
                    # Inizia configurazione prompt (edit message)
                    self.start_prompt_configuration_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_prompt'))
                
                elif call.data == 'start_amazon_config':
                    # Inizia configurazione Amazon (edit message)
                    self.start_amazon_affiliate_configuration_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_amazon'))
                
                elif call.data == 'cancel_cronjob_config':
                    # Annulla configurazione cronjob
                    user_id = call.from_user.id
                    if user_id in self.user_states:
                        del self.user_states[user_id]
                    self.show_cronjob_menu_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_annullata'))
                
                elif call.data == 'cancel_channel_config':
                    # Annulla configurazione canale
                    user_id = call.from_user.id
                    if user_id in self.user_states:
                        del self.user_states[user_id]
                    self.show_channel_config_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_annullata'))
                
                elif call.data == 'cancel_prompt_config':
                    self.cancel_prompt_config(call)
                
                elif call.data == 'cancel_amazon_config':
                    # Annulla configurazione Amazon
                    user_id = call.from_user.id
                    if user_id in self.user_states:
                        del self.user_states[user_id]
                    self.show_amazon_config_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_annullata'))
                
                elif call.data == 'cancel_test_prompt':
                    self.cancel_test_prompt(call)
                
                elif call.data == 'cancel_telegram_link_config':
                    # Annulla configurazione link telegram
                    user_id = call.from_user.id
                    if user_id in self.user_states:
                        del self.user_states[user_id]
                    self.show_categories_for_telegram_link_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_annullata'))
                
                elif call.data == 'add_admin_user':
                    # Inizia processo aggiunta admin
                    self.start_add_admin_process_edit(call, user_id)
                
                elif call.data.startswith('remove_admin_'):
                    # Rimuovi admin specifico
                    admin_user_id = int(call.data.split('_')[2])
                    self.confirm_remove_admin(call, admin_user_id)
                
                elif call.data.startswith('confirm_remove_admin_'):
                    # Conferma rimozione admin
                    admin_user_id = int(call.data.split('_')[3])
                    self.remove_admin_final(call, admin_user_id)
                
                elif call.data == 'cancel_remove_admin':
                    # Annulla rimozione admin
                    self.show_admin_management_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('rimozione_annullata'))
                
                elif call.data == 'cancel_admin_config':
                    # Annulla configurazione admin
                    user_id = call.from_user.id
                    if user_id in self.user_states:
                        del self.user_states[user_id]
                    self.show_admin_management_edit(call)
                    self.bot.answer_callback_query(call.id, self.get_text('configurazione_annullata'))
                
                elif call.data == 'toggle_auto_approval_enable':
                    # Abilita approvazione automatica
                    self.toggle_auto_approval(call, True)
                
                elif call.data == 'toggle_auto_approval_disable':
                    # Disabilita approvazione automatica
                    self.toggle_auto_approval(call, False)
                
                # Purchase Button Config callbacks
                elif call.data == 'show_purchase_button_config':
                    self.show_purchase_button_config_edit(call)
                elif call.data == 'start_purchase_button_config':
                    self.start_purchase_button_configuration(call)
                elif call.data == 'cancel_purchase_button_config':
                    self.cancel_purchase_button_config(call)
                
                # Test Prompt callbacks
                elif call.data == 'test_prompt':
                    self.show_test_categories(call)
                elif call.data.startswith('test_category_'):
                    category_id = int(call.data.split('_')[2])
                    self.show_test_products(call, category_id)
                elif call.data.startswith('test_product_'):
                    product_id = int(call.data.split('_')[2])
                    self.execute_prompt_test(call, product_id)
                
                elif call.data == 'already_approved':
                    # Messaggio già approvato
                    self.bot.answer_callback_query(call.id, self.get_text('messaggio_già_approvato'))
                
                elif call.data.startswith('view_product_'):
                    # Visualizza dettagli di un prodotto specifico
                    product_id = int(call.data.split('_')[2])
                    self.show_product_details(call, product_id)
                
                elif call.data.startswith('delete_product_'):
                    # Conferma eliminazione prodotto
                    product_id = int(call.data.split('_')[2])
                    self.confirm_delete_product(call, product_id)
                
                elif call.data == 'cancel_delete_product':
                    # Annulla eliminazione prodotto
                    self.bot.answer_callback_query(call.id, self.get_text('eliminazione_annullata'))
                    # Torna ai dettagli del prodotto (richiamare show_product_details)
                
                # Non chiamare answer_callback_query qui perché viene già gestito nelle singole funzioni
                
            except Exception as e:
                logger.error(f"Error in callback handler: {e}")
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                try:
                    self.bot.answer_callback_query(call.id, self.get_text('errore_interno'))
                except:
                    pass
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_all_messages(message):
            user_id = message.from_user.id
            
            if not self.is_user_authorized(user_id):
                self.bot.reply_to(message, self.get_text('spiacente_non_autorizzato'))
                return
            
            self.db.update_user_activity(user_id)
            
            # Controlla se l'utente è in un processo di aggiunta categoria, prodotto, link Telegram, configurazione cronjob o canale
            if user_id in self.user_states:
                if self.user_states[user_id]['action'] == 'adding_category':
                    self.handle_category_input(message)
                elif self.user_states[user_id]['action'] == 'adding_product':
                    self.handle_product_input(message)
                elif self.user_states[user_id]['action'] == 'adding_telegram_link':
                    self.handle_telegram_link_input(message)
                elif self.user_states[user_id]['action'] == 'configuring_cronjob':
                    self.handle_cronjob_configuration_input(message)
                elif self.user_states[user_id]['action'] == 'configuring_channel':
                    self.handle_channel_configuration_input(message)
                elif self.user_states[user_id]['action'] == 'configuring_prompt':
                    self.handle_prompt_configuration_input(message)
                elif self.user_states[user_id]['action'] == 'configuring_amazon_affiliate':
                    self.handle_amazon_affiliate_configuration_input(message)
                elif self.user_states[user_id]['action'] == 'adding_admin':
                    self.handle_add_admin_input(message)
                elif self.user_states[user_id]['action'] == 'configuring_purchase_button':
                    self.handle_purchase_button_configuration_input(message)
                return
            
            self.db.log_interaction(user_id, 'message', message.text[:100])
            
            # Risposta generica per messaggi non riconosciuti
            self.bot.reply_to(
                message, 
                self.get_text('non_ho_capito_il_messaggio')
            )
        
        logger.info("✅ Handlers registered successfully!")
    
    def show_categories_menu(self, chat_id: int):
        """Mostra il menu delle categorie con lista e pulsante aggiungi"""
        categories = self.db.get_all_categories()
        
        if categories:
            # Invia un messaggio per ogni categoria esistente
            for cat_id, name, description, telegram_link, created_by, created_at in categories:
                # Escape caratteri speciali per Markdown
                escaped_name = self.escape_markdown(name)
                escaped_desc = self.escape_markdown(description)
                
                category_text = f"📂 *{escaped_name}*\n"
                category_text += f"📝 {escaped_desc}\n"
                if telegram_link:
                    escaped_link = self.escape_markdown(telegram_link)
                    category_text += self.get_text('link_telegram')+": {escaped_link}\n"
                category_text += self.get_text('creata')+": {created_at[:16]}"
                
                # Keyboard con pulsante elimina
                keyboard = types.InlineKeyboardMarkup()
                delete_btn = types.InlineKeyboardButton(
                    self.get_text('elimina'), 
                    callback_data=f"delete_category_{cat_id}"
                )
                keyboard.add(delete_btn)
                
                self.bot.send_message(
                    chat_id, 
                    category_text, 
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
        
        # Messaggio finale con pulsante "Aggiungi categoria"
        if categories:
            final_text = f"📂 *" + self.get_text('categorie_total') + ": " + str(len(categories)) + "*\n\n" + self.get_text('clicca_qui_sotto_per_aggiungere_una_nuova_categoria')
        else:
            final_text = f"📂 *" + self.get_text('nessuna_categoria_presente') + "*\n\n" + self.get_text('clicca_qui_sotto_per_aggiungere_la_prima_categoria')
        
        keyboard = types.InlineKeyboardMarkup()
        add_btn = types.InlineKeyboardButton(
            self.get_text('aggiungi_categoria'), 
            callback_data="add_category"
        )
        keyboard.add(add_btn)
        
        self.bot.send_message(
            chat_id, 
            final_text, 
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    def start_add_category_process(self, call):
        """Inizia il processo di aggiunta categoria (modifica messaggio esistente)"""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        
        self.user_states[user_id] = {
            'action': 'adding_category',
            'step': 'name',
            'chat_id': chat_id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton(self.get_text('annulla'), callback_data="cancel_add_category")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                f"📂 *" + self.get_text('aggiunta_nuova_categoria') + "*\n\n"
                f"📝 " + self.get_text('inserisci_il_nome_della_categoria') + ":",
                chat_id,
                call.message.message_id,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error modifying add category message: {e}")
    
    def handle_category_input(self, message):
        """Gestisce l'input dell'utente durante l'aggiunta categoria"""
        user_id = message.from_user.id
        user_state = self.user_states[user_id]
        
        if user_state['step'] == 'name':
            # Salva il nome e chiedi la descrizione
            category_name = message.text.strip()
            
            if len(category_name) < 2 or len(category_name) > 50:
                self.bot.reply_to(
                    message,
                    f"❌ " + self.get_text('il_nome_deve_essere_tra_2_e_50_caratteri') + ". " + self.get_text('riprova') + ":"
                )
                return
            
            user_state['name'] = category_name
            user_state['step'] = 'description'
            
            # Keyboard con bottone annulla
            keyboard = types.InlineKeyboardMarkup()
            cancel_btn = types.InlineKeyboardButton(self.get_text('annulla'), callback_data="cancel_add_category")
            keyboard.add(cancel_btn)
            
            self.bot.reply_to(
                message,
                f"✅ " + self.get_text('nome_categoria') + ": *" + category_name + "*\n\n"
                f"📝 " + self.get_text('ora_inserisci_la_descrizione') + ":",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
        elif user_state['step'] == 'description':
            # Salva la descrizione e crea la categoria
            description = message.text.strip()
            
            if len(description) < 5 or len(description) > 200:
                self.bot.reply_to(
                    message,
                    f"❌ " + self.get_text('la_descrizione_deve_essere_tra_5_e_200_caratteri') + ". " + self.get_text('riprova') + ":"
                )
                return
            
            category_name = user_state['name']
            
            # Salva nel database
            success = self.db.add_category(category_name, description, user_id)
            
            if success:
                # Escape caratteri speciali per Markdown
                escaped_name = self.escape_markdown(category_name)
                escaped_desc = self.escape_markdown(description)
                
                self.bot.reply_to(
                    message,
                    f"✅ *" + self.get_text('categoria_creata_con_successo') + "!*\n\n"
                    f"📂 " + self.get_text('nome_categoria_creata') + ": {escaped_name}\n"
                    f"📝 " + self.get_text('descrizione_categoria_creata') + ": {escaped_desc}",
                    parse_mode='Markdown'
                )
                
                self.db.log_interaction(user_id, 'add_category', f"{self.get_text('categoria')}: {category_name}")
                logger.info(f"Category '{category_name}' created by user {user_id}")
            else:
                self.bot.reply_to(
                    message,
                    f"❌ *" + self.get_text('errore_categoria_già_esistente') + "*\n\n"
                    f"{self.get_text('una_categoria_con_il_nome')} '" + category_name + "' " + self.get_text('esiste_già') + ". "
                    f"{self.get_text('scegli_un_nome_diverso')}.",
                    parse_mode='Markdown'
                )
            
            # Rimuovi lo stato utente
            del self.user_states[user_id]
    
    def cancel_add_category_process(self, call):
        """Annulla il processo di aggiunta categoria"""
        user_id = call.from_user.id
        
        # Rimuovi lo stato utente se esiste
        if user_id in self.user_states:
            del self.user_states[user_id]
        
        # Torna al menu categorie
        self.show_categories_menu_edit(call)
        self.bot.answer_callback_query(call.id, self.get_text('aggiunta_categoria_annullata'))
    
    def delete_category_confirm(self, call, category_id: int):
        """Mostra conferma eliminazione categoria"""
        category = self.db.get_category_by_id(category_id)
        
        if not category:
            self.bot.answer_callback_query(call.id, self.get_text('categoria_non_trovata'))
            return
        
        cat_id, name, description, telegram_link, created_by, created_at = category
        
        confirm_text = f"🗑 *" + self.get_text('conferma_eliminazione') + "*\n\n"
        confirm_text += f"📂 " + self.get_text('nome') + ": {name}\n"
        confirm_text += f"📝 " + self.get_text('descrizione') + ": {description}\n\n"
        confirm_text += "⚠️ " + self.get_text('questa_azione_non_può_essere_annullata')
        
        keyboard = types.InlineKeyboardMarkup()
        confirm_btn = types.InlineKeyboardButton(
            f"✅ " + self.get_text('conferma') + "", 
            callback_data=f"confirm_delete_{category_id}"
        )
        cancel_btn = types.InlineKeyboardButton(
            f"❌ " + self.get_text('annulla') + "", 
            callback_data="cancel_delete"
        )
        keyboard.add(confirm_btn, cancel_btn)
        
        self.bot.edit_message_text(
            confirm_text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    def delete_category_final(self, call, category_id: int):
        """Elimina definitivamente la categoria"""
        category = self.db.get_category_by_id(category_id)
        
        if not category:
            self.bot.answer_callback_query(call.id, self.get_text('categoria_non_trovata'))
            return
        
        cat_id, name, description, telegram_link, created_by, created_at = category
        
        success = self.db.delete_category(category_id)
        
        if success:
            success_text = f"✅ <b>" + self.get_text('categoria_eliminata') + "</b>\n\n"
            success_text += f"📂 <b>" + self.escape_html(name) + "</b> " + self.get_text('è_stata_eliminata_con_successo') + "."
            
            # Keyboard con bottone per tornare alle categorie
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_alle_categorie') + "", callback_data="show_categories")
            keyboard.add(back_btn)
            
            try:
                self.bot.edit_message_text(
                    success_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                try:
                    self.bot.edit_message_caption(
                        call.message.chat.id,
                        call.message.message_id,
                        caption=success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    self.bot.send_message(
                        call.message.chat.id,
                        success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            
            self.bot.answer_callback_query(call.id, "✅ " + self.get_text('categoria_eliminata') + "")
            self.db.log_interaction(call.from_user.id, 'delete_category', f"{self.get_text('categoria')}: {name}")
            logger.info(f"Category '{name}' deleted by user {call.from_user.id}")
        else:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_nell_eliminazione') + "")
    
    # Metodi per gestire i prodotti
    def show_products_categories_menu(self, chat_id: int):
        """Mostra menu categorie per gestione prodotti"""
        categories = self.db.get_all_categories()
        
        menu_text = "📦 <b>" + self.get_text('gestione_prodotti') + "</b>\n\n"
        menu_text += self.get_text('seleziona_una_categoria_per_vedere_i_prodotti_o_aggiungi_un_nuovo_prodotto') + ":"
        
        # Crea keyboard con categorie + conteggio prodotti
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            # Conta prodotti in questa categoria
            products_count = len(self.db.get_products_by_category(cat_id))
            button_text = f"📂 {name} (" + str(products_count) + " " + self.get_text('prodotti') + ")"
            callback_data = f"view_category_products_{cat_id}_0"  # _0 per pagina 0
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        # Bottone per aggiungere nuovo prodotto
        add_btn = types.InlineKeyboardButton(
            f"➕ " + self.get_text('aggiungi_nuovo_prodotto') + "", 
            callback_data="add_new_product"
        )
        keyboard.add(add_btn)
        
        self.bot.send_message(
            chat_id,
            menu_text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def show_category_products(self, chat_id: int, category_id: int, page: int = 0, message_id: int = None):
        """Mostra prodotti di una categoria con paginazione"""
        category = self.db.get_category_by_id(category_id)
        if not category:
            self.bot.send_message(chat_id, "❌ " + self.get_text('categoria_non_trovata') + "")
            return
        
        cat_id, name, description, telegram_link, created_by, created_at = category
        products = self.db.get_products_by_category(category_id)
        
        if not products:
            no_products_text = f"📂 <b>" + self.escape_html(name) + "</b>\n\n"
            no_products_text += "📦 " + self.get_text('nessun_prodotto_in_questa_categoria') + "\n\n"
            no_products_text += self.get_text('usa_il_pulsante_qui_sotto_per_aggiungere_il_primo_prodotto') + ":"
            
            keyboard = types.InlineKeyboardMarkup()
            add_btn = types.InlineKeyboardButton(
                f"➕ " + self.get_text('aggiungi_prodotto') + "",  
                callback_data="add_new_product"
            )
            back_btn = types.InlineKeyboardButton(
                f"🔙 " + self.get_text('torna_al_menu') + "", 
                callback_data="back_to_products_menu"
            )
            keyboard.add(add_btn)
            keyboard.add(back_btn)
            
            if message_id:
                try:
                    self.bot.edit_message_text(
                        no_products_text,
                        chat_id,
                        message_id,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e:
                    # Se fallisce edit_message_text, prova con edit_message_caption
                    try:
                        self.bot.edit_message_caption(
                            chat_id,
                            message_id,
                            caption=no_products_text,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except Exception as e2:
                        # Fallback: invia nuovo messaggio
                        self.bot.send_message(
                            chat_id,
                            no_products_text,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
            else:
                self.bot.send_message(
                    chat_id,
                    no_products_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            return
        
        # Paginazione: 10 prodotti per pagina
        products_per_page = 10
        total_pages = (len(products) - 1) // products_per_page + 1
        start_idx = page * products_per_page
        end_idx = min(start_idx + products_per_page, len(products))
        current_products = products[start_idx:end_idx]
        
        # Testo header
        products_text = f"📂 <b>" + self.escape_html(name) + "</b>\n\n"
        products_text += f"📦 " + self.get_text('prodotti_maiuscolo') + " (" + str(len(products)) + " " + self.get_text('total') + ") - " + self.get_text('pagina') + " " + str(page + 1) + "/" + str(total_pages) + ":"
        
        # Keyboard con prodotti
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for product_id, amazon_url, title, added_by, created_at in current_products:
            # Accorcia il titolo se troppo lungo
            display_title = title[:50] + "..." if title and len(title) > 50 else (title or self.get_text('prodotto_amazon'))
            button_text = f"🛒 " + display_title
            callback_data = f"view_product_{product_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        # Bottoni navigazione se necessari
        nav_buttons = []
        if page > 0:
            nav_buttons.append(types.InlineKeyboardButton(
                f"⬅️ " + self.get_text('precedente') + "", 
                callback_data=f"view_category_products_{category_id}_{page-1}"
            ))
        if page < total_pages - 1:
            nav_buttons.append(types.InlineKeyboardButton(
                f"➡️ " + self.get_text('successiva') + "", 
                callback_data=f"view_category_products_{category_id}_{page+1}"
            ))
        
        if nav_buttons:
            keyboard.row(*nav_buttons)
        
        # Bottoni azioni
        add_btn = types.InlineKeyboardButton(
            f"➕ " + self.get_text('aggiungi_prodotto') + "", 
            callback_data="add_new_product"
        )
        back_btn = types.InlineKeyboardButton(
            f"🔙 " + self.get_text('torna_al_menu') + "", 
            callback_data="back_to_products_menu"
        )
        keyboard.add(add_btn)
        keyboard.add(back_btn)
        
        if message_id:
            try:
                self.bot.edit_message_text(
                    products_text,
                    chat_id,
                    message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                # Se fallisce edit_message_text, prova con edit_message_caption
                try:
                    self.bot.edit_message_caption(
                        chat_id,
                        message_id,
                        caption=products_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    # Fallback: invia nuovo messaggio
                    self.bot.send_message(
                        chat_id,
                        products_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
        else:
            self.bot.send_message(
                chat_id,
                products_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
    
    def show_products_categories_menu_edit(self, call):
        """Mostra menu categorie per gestione prodotti (edit message)"""
        categories = self.db.get_all_categories()
        
        menu_text = "📦 <b>" + self.get_text('gestione_prodotti') + "</b>\n\n"
        menu_text += self.get_text('seleziona_una_categoria_per_vedere_i_prodotti_o_aggiungi_un_nuovo_prodotto') + ":"
        
        # Crea keyboard con categorie + conteggio prodotti
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            # Conta prodotti in questa categoria
            products_count = len(self.db.get_products_by_category(cat_id))
            button_text = f"📂 {name} (" + str(products_count) + " " + self.get_text('prodotti') + ")"
            callback_data = f"view_category_products_{cat_id}_0"  # _0 per pagina 0
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        # Bottone per aggiungere nuovo prodotto
        add_btn = types.InlineKeyboardButton(
            f"➕ {self.get_text('aggiungi_nuovo_prodotto')}", 
            callback_data="add_new_product"
        )
        keyboard.add(add_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                menu_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            # Se fallisce edit_message_text, prova con edit_message_caption
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=menu_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                # Fallback: invia nuovo messaggio
                self.bot.send_message(
                    call.message.chat.id,
                    menu_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "📦 " + self.get_text('menu_prodotti'))
    
    def show_product_details(self, call, product_id: int):
        """Mostra dettagli di un prodotto specifico"""
        product = self.db.get_product_by_id(product_id)
        if not product:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('prodotto_non_trovato'))
            return
        
        product_id_db, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product
        
        # Prepara testo dettagli
        details_text = f"🛒 <b>" + self.get_text('dettagli_prodotto') + "</b>\n\n"
        details_text += f"📦 <b>" + self.escape_html(title or self.get_text('prodotto_amazon')) + "</b>\n\n"
        details_text += f"📂 " + self.get_text('categoria') + ": <b>" + self.escape_html(category_name or self.get_text('nessuna')) + "</b>\n"
        details_text += f"🆔 " + self.get_text('id_prodotto') + ": <code> " + str(product_id) + "</code>\n"
        details_text += f"📅 " + self.get_text('aggiunto') + ": " + created_at[:16] + "\n\n"
        details_text += f'🔗 <a href="{amazon_url}">{self.get_text("visualizza_su_amazon")}</a>'
        
        # Keyboard con azioni
        keyboard = types.InlineKeyboardMarkup()
        
        # Bottone per vedere su Amazon
        amazon_btn = types.InlineKeyboardButton(
            f"🛒 " + self.get_text('apri_su_amazon') + "",  
            url=amazon_url
        )
        
        # Bottone per eliminare prodotto
        delete_btn = types.InlineKeyboardButton(
            f"🗑 " + self.get_text('elimina_prodotto') + "", 
            callback_data=f"delete_product_{product_id}"
        )
        
        # Bottone per tornare alla categoria
        back_btn = types.InlineKeyboardButton(
            f"🔙 " + self.get_text('torna_alla_categoria') + "", 
            callback_data=f"view_category_products_{category_id}_0"
        )
        
        menu_btn = types.InlineKeyboardButton(
            f"🏠 " + self.get_text('menu_principale'), 
            callback_data="back_to_main_menu"
        )
        
        keyboard.add(amazon_btn)
        keyboard.add(delete_btn)
        keyboard.add(back_btn)
        keyboard.add(menu_btn)
        
        if image_url:
            try:
                self.bot.edit_message_media(
                    types.InputMediaPhoto(image_url, caption=details_text, parse_mode='HTML'),
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Error showing product image: {e}")
                self.bot.edit_message_text(
                    details_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        else:
            try:
                self.bot.edit_message_text(
                    details_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                # Se fallisce edit_message_text, prova con edit_message_caption
                try:
                    self.bot.edit_message_caption(
                        call.message.chat.id,
                        call.message.message_id,
                        caption=details_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    # Fallback: invia nuovo messaggio
                    self.bot.send_message(
                        call.message.chat.id,
                        details_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
        
        self.bot.answer_callback_query(call.id, f"📦 " + (title or self.get_text('prodotto'))[:30] + "...")
    
    def confirm_delete_product(self, call, product_id: int):
        """Mostra conferma eliminazione prodotto"""
        product = self.db.get_product_by_id(product_id)
        if not product:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('prodotto_non_trovato'))
            return
        
        product_id_db, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product
        
        confirm_text = f"🗑 <b>" + self.get_text('conferma_eliminazione') + "</b>\n\n"
        confirm_text += f"📦 <b>" + self.escape_html(title or self.get_text('prodotto_amazon')) + "</b>\n\n"
        confirm_text += f"📂 " + self.get_text('categoria') + ": <b>" + self.escape_html(category_name or self.get_text('nessuna')) + "</b>\n"
        confirm_text += f"🆔 " + self.get_text('id_prodotto') + ": <code> " + str(product_id) + "</code>\n\n"
        confirm_text += "⚠️ <b>" + self.get_text('questa_azione_non_può_essere_annullata') + "</b>\n"
        confirm_text += self.get_text('tutti_gli_sconti_associati_a_questo_prodotto_verranno_eliminati')
        
        keyboard = types.InlineKeyboardMarkup()
        confirm_btn = types.InlineKeyboardButton(
            f"✅ " + self.get_text('conferma_eliminazione'), 
            callback_data=f"confirm_delete_product_{product_id}"
        )
        cancel_btn = types.InlineKeyboardButton(
            f"❌ " + self.get_text('annulla') + "", 
            callback_data=f"view_product_{product_id}"  # Torna ai dettagli
        )
        keyboard.add(confirm_btn)
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                confirm_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            # Se fallisce edit_message_text, prova con edit_message_caption
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=confirm_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                # Fallback: invia nuovo messaggio
                self.bot.send_message(
                    call.message.chat.id,
                    confirm_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "⚠️ " + self.get_text('conferma_eliminazione'))
    
    def delete_product_final(self, call, product_id: int):
        """Elimina definitivamente il prodotto"""
        product = self.db.get_product_by_id(product_id)
        if not product:
            self.bot.answer_callback_query(call.id, "❌ "+ self.get_text('prodotto_non_trovato'))
            return
        
        product_id_db, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product
        
        # Elimina il prodotto dal database
        success = self.db.delete_product(product_id)
        
        if success:
            success_text = f"✅ <b>" + self.get_text('prodotto_eliminato') + "</b>\n\n"
            success_text += f"📦 " + self.escape_html(title or self.get_text('prodotto_amazon')) + " " + self.get_text('è_stato_eliminato_con_successo') + ".\n\n"
            success_text += f"🗑 " + self.get_text('eliminati_anche_tutti_gli_sconti_associati') + "."
            
            # Keyboard per tornare alla categoria
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton(
                f"🔙 " + self.get_text('torna_alla_categoria'), 
                callback_data=f"view_category_products_{category_id}_0"
            )
            menu_btn = types.InlineKeyboardButton(
                f"🏠 " + self.get_text('menu_principale'), 
                callback_data="back_to_main_menu"
            )
            keyboard.add(back_btn)
            keyboard.add(menu_btn)
            
            try:
                self.bot.edit_message_text(
                    success_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                # Se fallisce edit_message_text, prova con edit_message_caption
                try:
                    self.bot.edit_message_caption(
                        call.message.chat.id,
                        call.message.message_id,
                        caption=success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    # Fallback: invia nuovo messaggio
                    self.bot.send_message(
                        call.message.chat.id,
                        success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            
            self.db.log_interaction(call.from_user.id, 'delete_product', f'Prodotto: {title or "N/A"} (ID: {product_id})')
            logger.info(f"Product {product_id} deleted by user {call.from_user.id}")
            self.bot.answer_callback_query(call.id, "✅ "+ self.get_text('prodotto_eliminato'))
        else:
            self.bot.answer_callback_query(call.id, "❌ "+ self.get_text('errore_nell_eliminazione'))
    
    def show_help_menu_edit(self, call):
        """Mostra il menu help con bottoni inline (edit message)"""
        first_name = call.from_user.first_name
        
        # Stesso testo del comando /start e /help
        help_text = f"{self.get_text('welcome_greeting', name=first_name)}\n\n"
        help_text += f"{self.get_text('welcome_doublegram')}\n\n"
        help_text += f"{self.get_text('welcome_ready')}\n\n"
        help_text += f"{self.get_text('welcome_docs')}\n\n"
        help_text += f"{self.get_text('welcome_news')}\n\n"
        help_text += f"{self.get_text('main_menu_title')}\n\n"
        help_text += self.get_text('main_menu_description')
        
        # Crea keyboard con i bottoni richiesti
        keyboard = types.InlineKeyboardMarkup()
        
        # Riga 1: Categorie + Link Categorie (stesso row)
        categories_btn = types.InlineKeyboardButton(self.get_text('categories'), callback_data="show_categories")
        link_categories_btn = types.InlineKeyboardButton(self.get_text('link_categories'), callback_data="show_link_categories")
        keyboard.row(categories_btn, link_categories_btn)
        
        # Riga 2: Prodotti (da solo)
        products_btn = types.InlineKeyboardButton(self.get_text('products'), callback_data="show_products_menu")
        keyboard.add(products_btn)
        
        # Riga 3: Cronjob (da solo) 
        cronjob_btn = types.InlineKeyboardButton(self.get_text('cronjob'), callback_data="show_cronjob_menu")
        keyboard.add(cronjob_btn)
        
        # Riga 4: Canale Database (da solo)
        channel_btn = types.InlineKeyboardButton(self.get_text('channel_db'), callback_data="show_channel_config")
        keyboard.add(channel_btn)
        
        # Riga 5: Approvazione Automatica (da solo)
        auto_approval_btn = types.InlineKeyboardButton(self.get_text('auto_approval'), callback_data="show_auto_approval_config")
        keyboard.add(auto_approval_btn)
        
        # Riga 6: Prompt AI (da solo)
        prompt_btn = types.InlineKeyboardButton(self.get_text('prompt_ai'), callback_data="show_prompt_config")
        keyboard.add(prompt_btn)
        
        # Riga 7: Pulsante di acquisto (da solo)
        purchase_btn = types.InlineKeyboardButton(self.get_text('purchase_button'), callback_data="show_purchase_button_config")
        keyboard.add(purchase_btn)
        
        # Riga 8: Slug Amazon (da solo)
        amazon_btn = types.InlineKeyboardButton(self.get_text('slug_amazon'), callback_data="show_amazon_config")
        keyboard.add(amazon_btn)
        
        # Riga 9: Gestione Admin (da solo)
        admin_btn = types.InlineKeyboardButton(self.get_text('admin_management'), callback_data="show_admin_management")
        keyboard.add(admin_btn)
        
        # Riga 10: Impostazioni Lingua (da solo)
        language_btn = types.InlineKeyboardButton(self.get_text('language_settings'), callback_data="language_settings")
        keyboard.add(language_btn)
        
        try:
            self.bot.edit_message_text(
                help_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception as e:
            # Se fallisce edit_message_text, prova con edit_message_caption
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=help_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                # Fallback: invia nuovo messaggio
                self.bot.send_message(
                    call.message.chat.id,
                    help_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "📖 "+ self.get_text('menu_principale'))
    
    def show_categories_menu_edit(self, call):
        """Mostra il menu delle categorie con bottoni per ogni categoria (edit message)"""
        categories = self.db.get_all_categories()
        
        if categories:
            categories_text = "📂 <b>" + self.get_text('gestione_categorie') + "</b>\n\n"
            categories_text += f"📊 <b>" + self.get_text('categorie_total') + ": " + str(len(categories)) + "</b>\n\n"
            categories_text += self.get_text('clicca_su_una_categoria_per_visualizzarne_i_dettagli') + ":"
        else:
            categories_text = "📂 <b>" + self.get_text('gestione_categorie') + "</b>\n\n"
            categories_text += "❌ <b>" + self.get_text('nessuna_categoria_presente') + "</b>\n\n"
            categories_text += self.get_text('aggiungi_la_prima_categoria_per_iniziare')
        
        # Keyboard con bottoni per ogni categoria
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        # Aggiungi un bottone per ogni categoria
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            button_text = f"📂 " + name
            callback_data = f"view_category_{cat_id}"
            keyboard.add(button)
        
        # Bottone aggiungi categoria
        add_btn = types.InlineKeyboardButton("➕ " + self.get_text('aggiungi_categoria'), callback_data="add_category")
        keyboard.add(add_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                categories_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=categories_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    categories_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "📂 "+ self.get_text('categorie'))
    
    def show_category_details(self, call, category_id: int):
        """Mostra i dettagli di una categoria singola con opzione elimina"""
        category = self.db.get_category_by_id(category_id)
        
        if not category:
            self.bot.answer_callback_query(call.id, "❌ "+ self.get_text('categoria_non_trovata'))
            return
        
        cat_id, name, description, telegram_link, created_by, created_at = category
        
        # Conta i prodotti in questa categoria
        products_count = len(self.db.get_products_by_category(category_id))
        
        details_text = f"📂 <b>" + self.get_text('dettagli_categoria') + "</b>\n\n" 
        details_text += f"🏷️ <b>" + self.get_text('nome') + ":</b> " + self.escape_html(name) + "\n"
        details_text += f"📝 <b>" + self.get_text('descrizione') + ":</b> " + self.escape_html(description) + "\n"
        
        if telegram_link:
            details_text += f"🔗 <b>" + self.get_text('link_telegram') + ":</b> " + self.escape_html(telegram_link) + "\n"
        else:
            details_text += f"🔗 <b>" + self.get_text('link_telegram') + ":</b> " + self.get_text('non_configurato') + "\n"
        
        details_text += f"📦 <b>" + self.get_text('prodotti') + ":</b> " + str(products_count) + "\n"
        details_text += f"📅 <b>" + self.get_text('creata_il') + ":</b> " + created_at[:16] + "\n"
        details_text += f"👤 <b>" + self.get_text('creata_da') + ":</b> " + str(created_by) + "\n"
        
        # Keyboard con opzioni
        keyboard = types.InlineKeyboardMarkup()
        
        # Bottone elimina categoria
        delete_btn = types.InlineKeyboardButton("🗑 " + self.get_text('elimina_categoria'), callback_data=f"delete_category_{category_id}")
        keyboard.add(delete_btn)
        
        # Bottone back alle categorie
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_alle_categorie'), callback_data="show_categories")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                details_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=details_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    details_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, f"📂 {name}")
    
    def show_categories_for_telegram_link_edit(self, call):
        """Mostra le categorie disponibili per assegnare link Telegram (edit message)"""
        categories = self.db.get_all_categories()
        
        menu_text = "🔗 <b>" + self.get_text('gestione_link_telegram_per_categorie') + "</b>\n\n"
        menu_text += self.get_text('seleziona_la_categoria_a_cui_vuoi_assegnare_un_link_del_gruppo_telegram')
        
        # Crea keyboard con le categorie
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            # Indica se la categoria ha già un link
            if telegram_link:
                button_text = f"🔗 {name} (" + self.get_text('link_esistente') + ")"
            else:
                button_text = f"📂 {name} (" + self.get_text('nessun_link') + ")"
            
            callback_data = f"link_category_{cat_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                menu_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=menu_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    menu_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "🔗 "+ self.get_text('link_categorie'))
    
    def check_channel_before_cronjob(self, call):
        """Controlla se c'è un canale database configurato prima di mostrare il menu cronjob"""
        # Controlla se c'è un canale database configurato
        channel_config = self.db.get_channel_config()
        
        if not channel_config:
            # Nessun canale configurato, mostra messaggio di errore
            error_text = f"⚠️ <b>" + self.get_text('canale_database_richiesto') + "</b>\n\n"
            error_text += f"❌ " + self.get_text('prima_di_configurare_il_cronjob_devi_impostare_un_canale_database') + ".\n\n"
            error_text += f"💡 " + self.get_text('il_canale_database_è_necessario_per_inviare_le_notifiche_degli_sconti_per_lapprovazione') + ".\n\n"
            error_text += f"👉 " + self.get_text('vai_su_canale_database_per_configurarlo_prima') + "."
            
            # Keyboard con bottone torna al menu principale
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale') + "", callback_data="back_to_main_menu")
            keyboard.add(back_btn)
            
            try:
                self.bot.edit_message_text(
                    error_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Error modifying error cronjob message: {e}")
            
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('configura_prima_il_canale_database'))
        else:
            # Canale configurato, mostra il menu cronjob normale
            self.show_cronjob_menu_edit(call)
    
    def show_cronjob_menu_edit(self, call):
        """Mostra la configurazione cronjob (edit message)"""
        config = self.db.get_cronjob_config()
        
        if config:
            check_interval, product_delay, is_active, last_run, created_by = config
            status_emoji = "✅" if is_active else "❌"
            status_text = self.get_text('attivo') if is_active else self.get_text('inattivo')
        else:
            check_interval, product_delay, is_active = 60, 2, False
            status_emoji = "❌"
            status_text = self.get_text('non_configurato')
            last_run = None
        
        config_text = f"⏰ <b>" + self.get_text('configurazione_cronjob') + "</b>\n\n"
        config_text += f"{status_emoji} " + self.get_text('status') + ": <b>" + status_text + "</b>\n"
        config_text += f"🔄 " + self.get_text('controllo_ogni') + ": <b>" + str(check_interval) + " " + self.get_text('minuti') + "</b>\n" 
        config_text += f"⏱ " + self.get_text('pausa_tra_prodotti') + ": <b>" + str(product_delay) + " " + self.get_text('minuti') + "</b>\n"
        
        if last_run:
            config_text += f"🕒 " + self.get_text('ultima_esecuzione') + ": " + last_run[:16] + "\n"
        
        # Conta prodotti da monitorare
        products = self.db.get_all_products()
        config_text += f"\n📊 " + self.get_text('prodotti_da_monitorare') + ": <b>" + str(len(products)) + "</b>"
        
        # Keyboard con opzioni
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        config_btn = types.InlineKeyboardButton(
            f"⚙️ " + self.get_text('configura_intervalli'),  
            callback_data="cronjob_configure"
        )
        
        if is_active:
            toggle_btn = types.InlineKeyboardButton(
                f"⏸ " + self.get_text('ferma_cronjob'), 
                callback_data="cronjob_toggle"
            )
        else:
            toggle_btn = types.InlineKeyboardButton(
                f"▶️ " + self.get_text('avvia_cronjob'), 
                callback_data="cronjob_toggle"
            )
        
        status_btn = types.InlineKeyboardButton(
            f"📊 " + self.get_text('stato_dettagliato'), 
            callback_data="cronjob_status"
        )
        
        keyboard.add(config_btn, toggle_btn, status_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "⏰ " + self.get_text('cronjob'))
    
    def show_channel_config_edit(self, call):
        """Mostra configurazione canale database (edit message)"""
        config = self.db.get_channel_config()
        
        if config:
            channel_link, channel_id, is_active, created_by = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_database') + "</b>\n\n"
            config_text += f"🆔 " + self.get_text('id_canale') + ": <code>" + self.escape_html(channel_link) + "</code>\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n"
            config_text += f"👤 " + self.get_text('configurato_da') + ": " + str(created_by) + "\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_modificare_la_configurazione') + "."
        else:
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_database') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('nessun_canale_configurato') + "</b>\n\n"
            config_text += f"📝 " + self.get_text('il_canale_database_è_dove_il_bot_invierà_i_messaggi_per_lapprovazione_degli_sconti') + ".\n\n"
            config_text += f"⚠️ <b>" + self.get_text('importante') + ":</b> " + self.get_text('il_bot_deve_essere_amministratore_nel_canale') + "!\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_configurare') + "."
        
        # Keyboard con opzioni
        keyboard = types.InlineKeyboardMarkup()
        
        # Bottone per iniziare configurazione
        if config:
            config_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_configurazione'), callback_data="start_channel_config")
        else:
            config_btn = types.InlineKeyboardButton("➕ " + self.get_text('configura_canale'), callback_data="start_channel_config")
        
        keyboard.add(config_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "📢 "+ self.get_text('canale_database'))
    
    def show_amazon_config_edit(self, call):
        """Mostra configurazione slug Amazon (edit message)"""
        config = self.db.get_amazon_affiliate_config()
        
        if config:
            affiliate_tag, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"🏷 " + self.get_text('tag_attuale') + ": <code>" + self.escape_html(affiliate_tag) + "</code>\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n"
            config_text += f"👤 " + self.get_text('configurato_da') + ": " + created_by + "\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_modificare_la_configurazione') + "."
        else:
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('nessun_tag_configurato') + "</b>\n\n"
            config_text += f"📝 " + self.get_text('il_tag_di_affiliazione_amazon_verrà_aggiunto_ai_link_dei_prodotti') + ".\n\n"
            config_text += f"💡 " + self.get_text('esempio') + ": <code>miotag-21</code> (il tuo tag affiliazione Amazon)\n"
            config_text += f"🔗 " + self.get_text('i_link_diventeranno') + ": amazon.it/prodotto?tag=miotag-21\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_configurare') + "."
        
        # Keyboard con opzioni
        keyboard = types.InlineKeyboardMarkup()
        
        # Bottone per iniziare configurazione
        if config:
            config_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_tag') + "", callback_data="start_amazon_config")
        else:
            config_btn = types.InlineKeyboardButton("➕ " + self.get_text('configura_tag') + "", callback_data="start_amazon_config")
        
        keyboard.add(config_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "🔗 "+ self.get_text('slug_amazon'))
    
    def show_prompt_config_edit(self, call):
        """Mostra configurazione prompt AI (edit message)"""
        config = self.db.get_openai_prompt_config()
        
        if config:
            prompt_text, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_ai') + "</b>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n"
            config_text += f"👤 " + self.get_text('configurato_da') + ": " + str(created_by) + "\n"
            if updated_at:
                config_text += f"🔄 " + self.get_text('aggiornato') + ": " + updated_at[:16] + "\n\n"
            else:
                config_text += f"📅 " + self.get_text('creato') + ": " + created_at[:16] + "\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_modificare_il_prompt') + ".\n\n"
            config_text += f"⬇️ <i>" + self.get_text('prompt_attuale_mostrato_nel_messaggio_sotto') + "</i>"
        else:
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_ai') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('nessun_prompt_configurato') + "</b>\n\n"
            config_text += f"📝 " + self.get_text('il_prompt_personalizzato_verrà_usato_da_openai_per_migliorare_i_messaggi_degli_sconti') + ".\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_configurare') + "."
        
        # Keyboard con opzioni (solo per quando non c'è prompt configurato)
        keyboard = types.InlineKeyboardMarkup()
        
        # Se non c'è prompt, aggiungi pulsante per configurarlo
        if not config:
            config_btn = types.InlineKeyboardButton("➕ " + self.get_text('configura_prompt'), callback_data="start_prompt_config")
            keyboard.add(config_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        
        # Se c'è un prompt configurato, invia il prompt completo in un messaggio separato
        if config and prompt_text:
            prompt_message = f"📝 <b>" + self.get_text('prompt_ai_attuale') + ":</b>\n\n"
            prompt_message += f"<code>" + self.escape_html(prompt_text) + "</code>"
            
            # Keyboard per il messaggio del prompt
            keyboard_prompt = types.InlineKeyboardMarkup()
            test_btn = types.InlineKeyboardButton("🧪 " + self.get_text('testa_prompt'), callback_data="test_prompt")
            modify_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_prompt'), callback_data="start_prompt_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard_prompt.add(test_btn)
            keyboard_prompt.add(modify_btn)
            keyboard_prompt.add(menu_btn)
            
            # Invia il messaggio del prompt separatamente
            try:
                self.bot.send_message(
                    call.message.chat.id,
                    prompt_message,
                    parse_mode='HTML',
                    reply_markup=keyboard_prompt
                )
            except Exception as e:
                logger.error(f"Error sending prompt message: {e}")
        
        self.bot.answer_callback_query(call.id, "🤖 "+ self.get_text('prompt_ai'))
    
    def show_amazon_config_edit(self, call):
        """Mostra configurazione slug Amazon (edit message)"""
        config = self.db.get_amazon_affiliate_config()
        
        if config:
            affiliate_tag, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"🏷 <b>" + self.get_text('tag_attuale') + ":</b> <code>" + self.escape_html(affiliate_tag) + "</code>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n"
            config_text += f"👤 " + self.get_text('configurato_da') + ": " + str(created_by) + "\n"
            if updated_at:
                config_text += f"🔄 " + self.get_text('aggiornato') + ": " + updated_at[:16] + "\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_modificare_il_tag') + "."
        else:
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('nessun_tag_configurato') + "</b>\n\n"
            config_text += f"📝 " + self.get_text('il_tag_di_affiliazione_amazon_verrà_aggiunto_automaticamente_ai_link_amazon') + ".\n\n"
            config_text += f"💡 " + self.get_text('esempio') + ": <code>" + self.get_text('miotag-21') + "</code>\n"
            config_text += f"🔗 " + self.get_text('i_link_diventeranno') + ": amazon.it/prodotto?tag=" + self.get_text('miotag-21') + "\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_configurare') + "."
        
        # Keyboard con opzioni
        keyboard = types.InlineKeyboardMarkup()
        
        # Bottone per iniziare configurazione
        if config:
            config_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_tag'), callback_data="start_amazon_config")
        else:
            config_btn = types.InlineKeyboardButton("➕ " + self.get_text('configura_tag'), callback_data="start_amazon_config")
        
        keyboard.add(config_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "🔗 " + self.get_text('slug_amazon'))

    def is_valid_amazon_url(self, url: str) -> bool:
        """Valida se l'URL è un link Amazon valido"""
        amazon_patterns = [
            r'https?://(?:www\.)?amazon\.[a-z]{2,3}(?:\.[a-z]{2})?/.*',
            r'https?://(?:www\.)?amzn\.to/.*',
            r'https?://(?:www\.)?a\.co/.*'
        ]
        
        for pattern in amazon_patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True
        return False
    
    def extract_product_title_from_url(self, url: str) -> str:
        """Estrae il titolo del prodotto dall'URL Amazon utilizzando web scraping"""
        try:
            # Usa la funzione di scraping esistente per ottenere il titolo reale
            scrape_result = self.scrape_amazon_product(url)
            title = scrape_result.get('title', '')
            
            # Se il titolo è valido e diverso dal fallback generico, usalo
            if title and title != self.get_text('prodotto_amazon') and len(title.strip()) > 0:
                # Pulisci il titolo rimuovendo " - Amazon.it" e simili se presenti
                title = re.sub(r'\s*-\s*Amazon\.[a-z]{2,3}.*$', '', title)
                return title.strip()
            
            # Fallback: prova a estrarre l'ASIN dall'URL per un titolo generico più informativo
            if 'dp/' in url:
                asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
                if asin_match:
                    return f"{self.get_text('prodotto_amazon')} ({asin_match.group(1)})"
            
            return self.get_text('prodotto_amazon')
        except Exception as e:
            logger.error(f"Error extracting product title: {e}")
            # Fallback: prova almeno con l'ASIN
            try:
                if 'dp/' in url:
                    asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
                    if asin_match:
                        return f"{self.get_text('prodotto_amazon')} ({asin_match.group(1)})"
            except:
                pass
            return self.get_text('prodotto_amazon')
    
    def start_add_product_process(self, chat_id: int, user_id: int):
        """Inizia il processo di aggiunta prodotto (invia nuovo messaggio)"""
        self.user_states[user_id] = {
            'action': 'adding_product',
            'step': 'url',
            'chat_id': chat_id
        }
        
        self.bot.send_message(
            chat_id,
            f"🛒 <b>" + self.get_text('aggiunta_nuovo_prodotto_amazon') + "</b>\n\n" +
            f"🔗 " + self.get_text('inserisci_il_link_del_prodotto_amazon') + ":", 
            parse_mode='HTML'
        )
    
    def start_add_product_process_edit(self, call, user_id: int):
        """Inizia il processo di aggiunta prodotto (modifica messaggio esistente)"""
        self.user_states[user_id] = {
            'action': 'adding_product',
            'step': 'url',
            'chat_id': call.message.chat.id,
            'from_edit': True,  # Flag per indicare che proviene da edit
            'original_message_id': call.message.message_id  # Salva ID messaggio originale
        }
        
        add_product_text = f"🛒 <b>" + self.get_text('aggiunta_nuovo_prodotto_amazon') + "</b>\n\n"
        add_product_text += "🔗 " + self.get_text('inserisci_il_link_del_prodotto_amazon') + ":"
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton(
            f"❌ " + self.get_text('annulla'), 
            callback_data="back_to_products_menu"
        )
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                add_product_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            # Se fallisce edit_message_text, prova con edit_message_caption
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=add_product_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                # Fallback: invia nuovo messaggio
                self.bot.send_message(
                    call.message.chat.id,
                    add_product_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        
        self.bot.answer_callback_query(call.id, "➕ " + self.get_text('aggiungi_prodotto'))
    
    def handle_product_input(self, message):
        """Gestisce l'input dell'utente durante l'aggiunta prodotto"""
        user_id = message.from_user.id
        user_state = self.user_states[user_id]
        
        if user_state['step'] == 'url':
            amazon_url = message.text.strip()
            
            # Valida URL Amazon
            if not self.is_valid_amazon_url(amazon_url):
                self.bot.reply_to(
                    message,
                    f"❌ *" + self.get_text('link_non_valido') + "*\n\n"
                    f"{self.get_text('inserisci_un_link_amazon_valido')}.\n"
                    f"• {self.get_text('esempi_di_link_accettati')}:\n"
                    "• https://www.amazon.it/dp/...\n"
                    "• https://amzn.to/...\n"
                    "• https://a.co/...",
                    parse_mode='Markdown'
                )
                return
            
            # Estrae titolo del prodotto
            product_title = self.extract_product_title_from_url(amazon_url)
            
            # Salva il prodotto nel database (senza categoria per ora)
            product_id = self.db.add_product(
                amazon_url=amazon_url,
                title=product_title,
                added_by=user_id
            )
            
            # Rimuovi lo stato utente
            del self.user_states[user_id]
            
            # Mostra selezione categoria
            if user_state.get('from_edit', False):
                # Se proviene da edit, modifica il messaggio esistente
                self.show_category_selection_for_product_edit(
                    message.chat.id, 
                    product_id, 
                    amazon_url, 
                    product_title,
                    user_state.get('original_message_id')
                )
            else:
                # Altrimenti invia nuovo messaggio
                self.show_category_selection_for_product(message.chat.id, product_id, amazon_url, product_title)
            
            self.db.log_interaction(user_id, 'add_product', f'URL: {amazon_url[:50]}...')
            logger.info(f"Product added by user {user_id}: {amazon_url}")
    
    def show_category_selection_for_product(self, chat_id: int, product_id: int, amazon_url: str, product_title: str):
        """Mostra i pulsanti per selezionare la categoria del prodotto"""
        categories = self.db.get_all_categories()
        
        selection_text = f"✅ *" + self.get_text('prodotto_aggiunto_con_successo') + "!*\n\n"
        selection_text += f"🛒 " + product_title + "\n"
        selection_text += f"🔗 " + amazon_url[:50] + "'...' if len(amazon_url) > 50 else ''" + "\n\n"
        selection_text += "📂 *" + self.get_text('seleziona_la_categoria_per_questo_prodotto') + ":*"
        
        # Crea keyboard con le categorie
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            button_text = f"📂 " + name
            callback_data = f"assign_category_{product_id}_{cat_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        self.bot.send_message(
            chat_id,
            selection_text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def show_category_selection_for_product_edit(self, chat_id: int, product_id: int, amazon_url: str, product_title: str, message_id: int = None):
        """Mostra i pulsanti per selezionare la categoria del prodotto (NUOVO messaggio sempre)"""
        categories = self.db.get_all_categories()
        
        selection_text = f"✅ <b>" + self.get_text('prodotto_aggiunto_con_successo') + "!</b>\n\n"
        selection_text += f"🛒 " + self.escape_html(product_title) + "\n"
        selection_text += f"🔗 " + self.escape_html(amazon_url[:50]) + ("..." if len(amazon_url) > 50 else "") + "\n\n"
        selection_text += "📂 <b>" + self.get_text('seleziona_la_categoria_per_questo_prodotto') + ":</b>"
        
        # Crea keyboard con le categorie
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            button_text = f"📂 " + name
            callback_data = f"assign_category_{product_id}_{cat_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        # SEMPRE invia nuovo messaggio per la selezione categoria
        self.bot.send_message(
            chat_id,
            selection_text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def assign_product_to_category(self, call, product_id: int, category_id: int):
        """Assegna un prodotto a una categoria"""
        # Ottieni informazioni prodotto e categoria
        product = self.db.get_product_by_id(product_id)
        category = self.db.get_category_by_id(category_id)
        
        if not product or not category:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('prodotto_o_categoria_non_trovati'))
            return
        
        # Aggiorna categoria del prodotto
        success = self.db.update_product_category(product_id, category_id)
        
        if success:
            product_title = product[2] if product[2] else self.get_text('prodotto_amazon')
            category_name = category[1]
            
            success_text = f"✅ <b>" + self.get_text('prodotto_assegnato_alla_categoria') + "!</b>\n\n"
            success_text += f"🛒 " + self.escape_html(product_title) + "\n"
            success_text += f"📂 " + self.get_text('categoria') + ": <b>" + self.escape_html(category_name) + "</b>\n\n"
            success_text += f"🔗 " + self.escape_html(product[1])
            
            # Aggiungi pulsante per tornare al menu prodotti
            keyboard = types.InlineKeyboardMarkup()
            back_button = types.InlineKeyboardButton("🔙 " + self.get_text('torna_al_menu_prodotti'), callback_data="back_to_products_menu")
            keyboard.add(back_button)
            
            try:
                self.bot.edit_message_text(
                    success_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                # Se fallisce edit_message_text, prova con edit_message_caption
                try:
                    self.bot.edit_message_caption(
                        call.message.chat.id,
                        call.message.message_id,
                        caption=success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    # Fallback: invia nuovo messaggio
                    self.bot.send_message(
                        call.message.chat.id,
                        success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            
            self.bot.answer_callback_query(call.id, "✅ " + self.get_text('prodotto_assegnato_alla_categoria'))
            self.db.log_interaction(call.from_user.id, 'assign_category', f"{self.get_text('prodotto')} {product_id} -> {self.get_text('categoria')} {category_name}")
            logger.info(f"{self.get_text('prodotto')} {product_id} {self.get_text('assegnato_alla_categoria')} {category_name} {self.get_text('da_utente')} {call.from_user.id}")
        else:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_nell_assegnazione'))
    
    # Metodi per gestire i link Telegram delle categorie
    def show_categories_for_telegram_link(self, chat_id: int):
        """Mostra le categorie disponibili per assegnare link Telegram"""
        categories = self.db.get_all_categories()
        
        menu_text = "🔗 *" + self.get_text('gestione_link_telegram_per_categorie') + "*\n\n"
        menu_text += self.get_text('seleziona_la_categoria_a_cui_vuoi_assegnare_un_link_del_gruppo_telegram')
        
        # Crea keyboard con le categorie
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            # Indica se la categoria ha già un link
            if telegram_link:
                button_text = f"🔗 {name} (" + self.get_text('link_esistente') + ")"
            else:
                button_text = f"📂 {name} (" + self.get_text('nessun_link') + ")"
            
            callback_data = f"link_category_{cat_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        self.bot.send_message(
            chat_id,
            menu_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    def start_telegram_link_process(self, call, category_id: int):
        """Inizia il processo di assegnazione link Telegram a una categoria"""
        category = self.db.get_category_by_id(category_id)
        
        if not category:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('categoria_non_trovata'))
            return
        
        cat_id, name, description, telegram_link, created_by, created_at = category
        
        # Imposta lo stato utente
        self.user_states[call.from_user.id] = {
            'action': 'adding_telegram_link',
            'category_id': category_id,
            'category_name': name,
            'chat_id': call.message.chat.id
        }
        
        # Messaggio con info categoria corrente
        # Escape caratteri speciali per HTML 
        escaped_name = self.escape_html(name)
        escaped_desc = self.escape_html(description)
        
        link_text = f"🔗 <b>" + self.get_text('assegnazione_link_telegram') + "</b>\n\n"
        link_text += f"📂 " + self.get_text('categoria') + ": <b>" + escaped_name + "</b>\n"
        link_text += f"📝 " + self.get_text('descrizione') + ": " + escaped_desc + "\n"
        
        if telegram_link:
            escaped_link = self.escape_html(telegram_link)
            link_text += f"\n🔗 " + self.get_text('link_attuale') + ": <code>" + escaped_link + "</code>\n"
            link_text += f"\n💡 " + self.get_text('invia_il_nuovo_link_per_sostituire_quello_esistente') + ":"
        else:
            link_text += f"\n📱 " + self.get_text('nessun_link_assegnato') + "\n"
            link_text += f"\n💡 " + self.get_text('invia_il_link_del_gruppo_telegram_per_questa_categoria') + ":"
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_telegram_link_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                link_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=link_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    link_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        
        self.bot.answer_callback_query(call.id, f"✅ " + self.get_text('selezionata_categoria') + ": " + name)
    
    def handle_telegram_link_input(self, message):
        """Gestisce l'input del link Telegram dall'utente"""
        user_id = message.from_user.id
        user_state = self.user_states[user_id]
        
        # Non serve più controllo /annulla, ora c'è il bottone
        
        telegram_link = message.text.strip()
        category_id = user_state['category_id']
        category_name = user_state['category_name']
        
        # Aggiorna il link nel database
        success = self.db.update_category_telegram_link(category_id, telegram_link)
        
        if success:
            # Escape caratteri speciali HTML nel link
            escaped_link = self.escape_html(telegram_link)
            escaped_category = self.escape_html(category_name)
            
            success_text = f"✅ <b>" + self.get_text('link_telegram_assegnato_con_successo') + "!</b>\n\n"
            success_text += f"📂 " + self.get_text('categoria') + ": <b>" + escaped_category + "</b>\n"
            success_text += f"🔗 " + self.get_text('link') + ": <code>" + escaped_link + "</code>"
            
            # Keyboard con bottone per tornare al menu link categorie
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_a_link_categorie'), callback_data="show_link_categories")
            keyboard.add(back_btn)
            
            self.bot.reply_to(
                message,
                success_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
            self.db.log_interaction(user_id, 'assign_telegram_link', f"{self.get_text('categoria')}: {category_name}")
            logger.info(f"{self.get_text('link_telegram_assegnato_alla_categoria')} '{category_name}' {self.get_text('da_utente')} {user_id}")
        else:
            self.bot.reply_to(
                message,
                "❌ <b>" + self.get_text('errore_nell_assegnazione') + "</b>\n\n" + self.get_text('si_è_verificato_un_errore_durante_lassegnazione_del_link_riprova') + ".",
                parse_mode='HTML'
            )
        
        # Rimuovi lo stato utente
        del self.user_states[user_id]
    
    # Metodi per gestire il cronjob
    def show_cronjob_config(self, chat_id: int, user_id: int):
        """Mostra la configurazione attuale del cronjob"""
        config = self.db.get_cronjob_config()
        
        if config:
            check_interval, product_delay, is_active, last_run, created_by = config
            status_emoji = "✅" if is_active else "❌"
            status_text = self.get_text('attivo') if is_active else self.get_text('inattivo')
        else:
            check_interval, product_delay, is_active = 60, 2, False
            status_emoji = "❌"
            status_text = self.get_text('non_configurato')
            last_run = None
        
        config_text = f"⏰ *" + self.get_text('configurazione_cronjob') + "*\n\n"
        config_text += f"{status_emoji} " + self.get_text('status') + ": *" + status_text + "*\n"
        config_text += f"🔄 " + self.get_text('controllo_ogni') + ": *" + check_interval + " minuti*\n"
        config_text += f"⏱ " + self.get_text('pausa_tra_prodotti') + ": *" + product_delay + " minuti*\n"
        
        if last_run:
            config_text += f"🕒 " + self.get_text('ultima_esecuzione') + ": " + last_run[:16] + "\n"
        
        # Conta prodotti da monitorare
        products = self.db.get_all_products()
        config_text += f"\n📊 " + self.get_text('prodotti_da_monitorare') + ": *" + len(products) + "*"
        
        # Keyboard con opzioni
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        config_btn = types.InlineKeyboardButton(
            f"⚙️ " + self.get_text('configura_intervalli'),  
            callback_data="cronjob_configure"
        )
        
        if is_active:
            toggle_btn = types.InlineKeyboardButton(
                f"⏸ " + self.get_text('ferma_cronjob'), 
                callback_data="cronjob_toggle"
            )
        else:
            toggle_btn = types.InlineKeyboardButton(
                f"▶️ " + self.get_text('avvia_cronjob'), 
                callback_data="cronjob_toggle"
            )
        
        status_btn = types.InlineKeyboardButton(
            f"📊 " + self.get_text('stato_dettagliato'), 
            callback_data="cronjob_status"
        )
        
        keyboard.add(config_btn, toggle_btn, status_btn)
        
        self.bot.send_message(
            chat_id,
            config_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    def start_cronjob_configuration(self, call):
        """Inizia il processo di configurazione cronjob"""
        self.user_states[call.from_user.id] = {
            'action': 'configuring_cronjob',
            'step': 'check_interval',
            'chat_id': call.message.chat.id
        }
        
        config_text = f"⚙️ <b>" + self.get_text('configurazione_cronjob') + "</b>\n\n"
        config_text += f"🔄 " + self.get_text('inserisci_ogni_quanti_minuti_deve_essere_eseguito_il_controllo_prezzi') + "\n\n"
        config_text += f"💡 " + self.get_text('esempi') + ":\n"
        config_text += f"• 30 = " + self.get_text('ogni_30_minuti') + "\n"
        config_text += f"• 60 = " + self.get_text('ogni_ora') + "\n"
        config_text += f"• 120 = " + self.get_text('ogni_2_ore') + "\n\n"
        config_text += f"📝 " + self.get_text('invia_un_numero_intero') + ":"
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_cronjob_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
    
    def handle_cronjob_configuration_input(self, message):
        """Gestisce l'input per la configurazione cronjob"""
        user_id = message.from_user.id
        user_state = self.user_states[user_id]
        
        # Non serve più controllo /annulla, ora c'è il bottone
        
        try:
            value = int(message.text.strip())
        except ValueError:
            self.bot.reply_to(
                message,
                "❌ <b>" + self.get_text('valore_non_valido') + "</b>\n\n" + self.get_text('inserisci_un_numero_intero') + ":",
                parse_mode='HTML'
            )
            return
        
        if user_state['step'] == 'check_interval':
            if value < 5:
                self.bot.reply_to(
                    message,
                    "❌ *" + self.get_text('intervallo_troppo_breve') + "*\n\n" + self.get_text('lintervallo_minimo_è_5_minuti_per_evitare_socarico') + "."
                )
                return
            
            user_state['check_interval'] = value
            user_state['step'] = 'product_delay'
            
            step2_text = f"✅ " + self.get_text('intervallo_controllo') + ": <b>" + value + " minuti</b>\n\n"
            step2_text += f"⏱ " + self.get_text('ora_inserisci_quanti_minuti_di_pausa_devono_passare_tra_lanalisi_di_un_prodotto_e_il_successivo') + ":\n\n"
            step2_text += f"💡 " + self.get_text('esempi') + ":\n"
            step2_text += f"• 1 = " + self.get_text('1_minuto_di_pausa') + "\n"
            step2_text += f"• 2 = " + self.get_text('2_minuti_di_pausa') + "\n"
            step2_text += f"• 5 = " + self.get_text('5_minuti_di_pausa') + "\n\n"
            step2_text += f"⚠️ " + self.get_text('pausa_più_lunga_=_meno_rischio_di_essere_bloccati_da_amazon')
            
            # Keyboard con bottone annulla
            keyboard = types.InlineKeyboardMarkup()
            cancel_btn = types.InlineKeyboardButton(f"❌ " + self.get_text('annulla'), callback_data="cancel_cronjob_config")
            keyboard.add(cancel_btn)
            
            self.bot.reply_to(
                message,
                step2_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
        elif user_state['step'] == 'product_delay':
            if value < 1:
                self.bot.reply_to(
                    message,
                    "❌ *" + self.get_text('pausa_troppo_breve') + "*\n\n" + self.get_text('la_pausa_minima_è_1_minuto_per_evitare_di_essere_bloccati') + "."
                )
                return
            
            check_interval = user_state['check_interval']
            
            # Salva configurazione
            success = self.db.update_cronjob_config(
                check_interval=check_interval,
                product_delay=value,
                is_active=False,  # Inizialmente inattivo
                created_by=user_id
            )
            
            if success:
                self.bot.reply_to(
                    message,
                    f"✅ *" + self.get_text('configurazione_salvata') + "!*\n\n"
                    f"🔄 " + self.get_text('controllo_ogni') + ": *" + check_interval + " minuti*\n"
                    f"⏱ " + self.get_text('pausa_tra_prodotti') + ": *" + value + " minuti*\n\n"
                    f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_modificare_la_configurazione') + "!",
                    parse_mode='Markdown'
                )
                
                self.db.log_interaction(user_id, 'configure_cronjob', f"{self.get_text('intervallo')}: " + check_interval + "min, " + self.get_text('pausa') + ": " + value + "min")
                logger.info(f"Cronjob configured by user {user_id}: {check_interval}min/{value}min")
            else:
                self.bot.reply_to(
                    message,
                    "❌ *" + self.get_text('errore_nel_salvataggio') + "*\n\n" + self.get_text('si_è_verificato_un_errore_riprova') + ".",
                    parse_mode='Markdown'
                )
            
            # Rimuovi stato utente
            del self.user_states[user_id]
    
    def toggle_cronjob(self, call):
        """Attiva o disattiva il cronjob"""
        config = self.db.get_cronjob_config()
        
        if not config:
            self.bot.edit_message_text(
                "❌ *" + self.get_text('cronjob_non_configurato') + "*\n\n" + self.get_text('prima_configura_gli_intervalli_usando_il_pulsante_configura_intervalli') + ".",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown'
            )
            return
        
        check_interval, product_delay, is_active, last_run, created_by = config
        new_status = not is_active
        
        # Aggiorna stato nel database
        success = self.db.update_cronjob_config(
            check_interval=check_interval,
            product_delay=product_delay,
            is_active=new_status,
            created_by=created_by
        )
        
        if success:
            if new_status:
                # Avvia cronjob
                self.start_price_monitoring_thread()
                self.bot.answer_callback_query(call.id, "✅ " + self.get_text('cronjob_attivato'))
                self.db.log_interaction(call.from_user.id, 'start_cronjob', "{self.get_text('cronjob_avviato')}")
                logger.info(f"Cronjob started by user {call.from_user.id}")
            else:
                # Ferma cronjob
                self.stop_price_monitoring_thread()
                self.bot.answer_callback_query(call.id, "⏸ " + self.get_text('cronjob_fermato'))
                self.db.log_interaction(call.from_user.id, 'stop_cronjob', "{self.get_text('cronjob_fermato')}")
                logger.info(f"Cronjob stopped by user {call.from_user.id}")
            
            # Aggiorna il menu mantenendo i bottoni ma con lo status aggiornato
            self.show_cronjob_menu_edit(call)
        else:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_nell_aggiornamento'))
    
    def show_cronjob_status(self, call):
        """Mostra stato dettagliato del cronjob"""
        config = self.db.get_cronjob_config()
        
        if not config:
            status_text = "❌ *" + self.get_text('cronjob_non_configurato') + "*"
        else:
            check_interval, product_delay, is_active, last_run, created_by = config
            
            status_text = f"📊 *" + self.get_text('stato_dettagliato_cronjob') + "*\n\n"
            status_text += f"🔄 " + self.get_text('controllo_ogni') + ": " + str(check_interval) + " " + self.get_text('minuti') + "\n" 
            status_text += f"⏱ " + self.get_text('pausa_tra_prodotti') + ": " + str(product_delay) + " " + self.get_text('minuti') + "\n"
            status_text += f"📊 Status: {'✅ ' + self.get_text('attivo') if is_active else '❌ ' + self.get_text('inattivo')}\n"
            
            if last_run:
                status_text += f"🕒 " + self.get_text('ultima_esecuzione') + ": " + str(last_run[:16]) + "\n"
            
            # Informazioni thread
            if self.cronjob_running:
                status_text += f"🧵 Thread: ✅ " + self.get_text('in_esecuzione') + "\n"
            else:
                status_text += f"🧵 Thread: ❌ " + self.get_text('fermo') + "\n"
            
            # Conta prodotti
            products = self.db.get_all_products()
            status_text += f"📦 " + self.get_text('prodotti_monitorati') + ": " + str(len(products)) + "\n"
        
        # Keyboard con bottone indietro
        keyboard = types.InlineKeyboardMarkup()
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_al_cronjob'), callback_data="show_cronjob_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                status_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=status_text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    status_text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
        
        self.bot.answer_callback_query(call.id, "📊 " + self.get_text('stato_dettagliato'))
    
    # Metodi per il web scraping e monitoraggio prezzi
    def scrape_amazon_product(self, url: str) -> Dict[str, Any]:
        """Scraping di un prodotto Amazon per rilevare sconti e dettagli prodotto"""
        try:
            headers = {
                'User-Agent': self.user_agent.random,
                'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Estrae il titolo del prodotto dal meta title
            title = self.get_text('prodotto_amazon')
            title_meta = soup.find('meta', {'name': 'title'})
            if title_meta and title_meta.get('content'):
                title = title_meta.get('content').strip()
            else:
                # Fallback: cerca il titolo nella pagina
                title_element = soup.find('span', {'id': 'productTitle'})
                if title_element:
                    title = title_element.get_text(strip=True)
            
            # Estrae l'URL dell'immagine principale
            image_url = None
            img_element = soup.find('img', {'id': 'landingImage'})
            if img_element:
                image_url = img_element.get('src')
                # Se non c'è src, prova con data-old-hires per l'immagine ad alta risoluzione
                if not image_url:
                    image_url = img_element.get('data-old-hires')
            
            # Cerca il div dello sconto
            discount_element = soup.find('span', {
                'class': lambda x: x and 'savingsPercentage' in x and 'a-color-price' in x
            })
            
            result = {
                'title': title,
                'image_url': image_url,
                'has_discount': False
            }
            
            if not discount_element:
                # Nessuno sconto trovato, ma restituisce comunque titolo e immagine
                return result
            
            # Estrae percentuale sconto
            discount_text = discount_element.get_text(strip=True)
            discount_match = re.search(r'-(\d+)%', discount_text)
            
            if not discount_match:
                return result
            
            discount_percentage = int(discount_match.group(1))
            
            # Cerca prezzo scontato (finale)
            discounted_price_element = soup.find('span', {
                'class': lambda x: x and 'priceToPay' in x
            })
            
            discounted_price = "N/A"
            if discounted_price_element:
                price_text = discounted_price_element.get_text(strip=True)
                # Estrae il prezzo (formato: 139,90€)
                price_match = re.search(r'(\d+(?:,\d+)?)\s*€', price_text)
                if price_match:
                    discounted_price = price_match.group(1) + "€"
            
            # Cerca prezzo originale
            original_price_element = soup.find('span', {
                'class': lambda x: x and 'basisPrice' in x
            })
            
            original_price = "N/A"
            if original_price_element:
                price_text = original_price_element.get_text(strip=True)
                # Estrae il prezzo dal testo (formato: "Prezzo consigliato: 145,90€")
                price_match = re.search(r'(\d+(?:,\d+)?)\s*€', price_text)
                if price_match:
                    original_price = price_match.group(1) + "€"
            
            # Verifica che entrambi i prezzi siano validi per considerarlo un vero sconto
            if original_price != "N/A" and discounted_price != "N/A":
                result.update({
                    'has_discount': True,
                    'discount_percentage': discount_percentage,
                    'discounted_price': discounted_price,
                    'original_price': original_price
                })
            else:
                # Se manca il prezzo originale o scontato, non è un vero sconto
                logger.info(f"{self.get_text('sconto_ignorato')}: " + self.get_text('prezzo_originale') + "='{original_price}', " + self.get_text('prezzo_scontato') + "='{discounted_price}'")
            
            return result
            
        except requests.RequestException as e:
            logger.error(f"Error in HTTP request for {url}: {e}")
            return {'error': f"{self.get_text('errore_di_connessione')}: " + str(e)}
        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return {'error': f"{self.get_text('errore_nel_parsing')}: " + str(e)}
    
    def start_price_monitoring_thread(self):
        """Avvia il thread per il monitoraggio prezzi"""
        if self.cronjob_running:
            logger.warning("Cronjob already running")
            return
        
        self.cronjob_running = True
        self.cronjob_thread = threading.Thread(target=self.price_monitoring_loop, daemon=True)
        self.cronjob_thread.start()
        logger.info("Thread cronjob started")
    
    def stop_price_monitoring_thread(self):
        """Ferma il thread per il monitoraggio prezzi"""
        self.cronjob_running = False
        if self.cronjob_thread and self.cronjob_thread.is_alive():
            logger.info("Stopping thread cronjob...")
        else:
            logger.info("Thread cronjob stopped")
    
    def price_monitoring_loop(self):
        """Loop principale del monitoraggio prezzi"""
        logger.info("Starting price monitoring loop")
        
        while self.cronjob_running:
            try:
                config = self.db.get_cronjob_config()
                if not config or not config[2]:  # is_active
                    logger.info("Cronjob disabled, exiting loop")
                    break
                
                check_interval, product_delay, is_active, last_run, created_by = config
                
                # Ottieni tutti i prodotti da monitorare
                products = self.db.get_all_products()
                
                if not products:
                    logger.info("No products to monitor")
                else:
                    logger.info(f"Starting check of {len(products)} products")
                    
                    for product in products:
                        if not self.cronjob_running:
                            break
                        
                        product_id, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product
                        
                        logger.info(f"Checking product {product_id}: {title or 'No title'}")
                        
                        # Scraping del prodotto
                        scrape_result = self.scrape_amazon_product(amazon_url)
                        
                        if 'error' in scrape_result:
                            logger.error(f"Error scraping product {product_id}: {scrape_result['error']}")
                        else:
                            # Aggiorna titolo e immagine se necessario
                            scraped_title = scrape_result.get('title')
                            scraped_image = scrape_result.get('image_url')
                            
                            if scraped_title and scraped_title != title:
                                self.db.update_product_details(product_id, title=scraped_title)
                                title = scraped_title  # Aggiorna per uso successivo
                            
                            if scraped_image and scraped_image != image_url:
                                self.db.update_product_details(product_id, image_url=scraped_image)
                                image_url = scraped_image  # Aggiorna per uso successivo
                            
                            # Controlla se c'è uno sconto
                            if scrape_result.get('has_discount', False):
                                # Prodotto in sconto
                                discount_percentage = scrape_result['discount_percentage']
                                original_price = scrape_result['original_price']
                                discounted_price = scrape_result['discounted_price']
                                
                                # Controlla se i dati sono cambiati
                                if self.db.discount_data_changed(product_id, discount_percentage, original_price, discounted_price):
                                    # Salva nuovo sconto
                                    discount_id = self.db.add_product_discount(
                                        product_id=product_id,
                                        discount_percentage=discount_percentage,
                                        original_price=original_price,
                                        discounted_price=discounted_price
                                    )
                                    
                                    logger.info(f"New discount found for product {product_id}: -{discount_percentage}%")
                                    
                                    # Invia notifica al canale di approvazione
                                    self.send_discount_notification(product_id, discount_id, {
                                        'title': title,
                                        'image_url': image_url,
                                        'amazon_url': amazon_url,
                                        'category_name': category_name,
                                        'discount_percentage': discount_percentage,
                                        'original_price': original_price,
                                        'discounted_price': discounted_price
                                    })
                                else:
                                    logger.debug(f"Discount unchanged for product {product_id}")
                            else:
                                logger.debug(f"No discount for product {product_id}")
                        
                        # Pausa tra prodotti
                        if self.cronjob_running:
                            time.sleep(product_delay * 60)  # Converti minuti in secondi
                
                # Aggiorna timestamp ultima esecuzione
                self.db.update_cronjob_last_run()
                
                # Pausa prima del prossimo ciclo
                if self.cronjob_running:
                    logger.info(f"Check completed, pause of {check_interval} minutes")
                    time.sleep(check_interval * 60)  # Converti minuti in secondi
                
            except Exception as e:
                logger.error(f"Error in price monitoring loop: {e}")
                time.sleep(60)  # Pausa di 1 minuto in caso di errore
        
        self.cronjob_running = False
        logger.info("Price monitoring loop terminated")
    
    # Metodi per gestire il canale di approvazione
    def start_channel_configuration_edit(self, call):
        """Inizia il processo di configurazione canale (edit message)"""
        user_id = call.from_user.id
        config = self.db.get_channel_config()
        
        if config:
            channel_link, channel_id, is_active, created_by = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_approvazione') + "</b>\n\n"
            config_text += f"🆔 " + self.get_text('id_attuale') + ": <code>" + channel_link + "</code>\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_id_del_canale_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_approvazione') + "</b>\n\n"
            config_text += f"❌ " + self.get_text('nessun_canale_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_nuovo_id_del_canale_per_aggiornare_la_configurazione') + "\n\n"
            config_text += f"⚠️ <b>" + self.get_text('importante') + ":</b> " + self.get_text('il_bot_deve_essere_già_amministratore_nel_canale') + "!\n\n"
            config_text += f"💡 " + self.get_text('formato_esempio') + ": <code>-1001234567890</code> (" + self.get_text('id_numerico_del_canale_privato') + ")\n"
            config_text += f"📍 " + self.get_text('come_trovare_l_id') + ": " + self.get_text('aggiungi_userinfobot_al_canale_e_scrivi_id')
        
        self.user_states[user_id] = {
            'action': 'configuring_channel',
            'chat_id': call.message.chat.id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_channel_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error editing channel config message: {e}")
            # Fallback: invia nuovo messaggio se edit fallisce
            self.bot.send_message(
                call.message.chat.id, 
                config_text, 
                parse_mode='HTML',
                reply_markup=keyboard
            )

    def start_channel_configuration(self, chat_id: int, user_id: int):
        """Inizia il processo di configurazione canale"""
        config = self.db.get_channel_config()
        
        if config:
            channel_link, channel_id, is_active, created_by = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_approvazione') + "</b>\n\n"
            config_text += f"🆔 " + self.get_text('id_attuale') + ": <code>" + channel_link + "</code>\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_id_del_canale_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_approvazione') + "</b>\n\n"
            config_text += f"❌ " + self.get_text('nessun_canale_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_nuovo_id_del_canale_per_aggiornare_la_configurazione') + "\n\n"
            config_text += f"⚠️ <b>" + self.get_text('importante') + ":</b> " + self.get_text('il_bot_deve_essere_già_amministratore_nel_canale') + "!\n\n"
            config_text += f"💡 " + self.get_text('formato_esempio') + ": <code>-1001234567890</code> (" + self.get_text('id_numerico_del_canale_privato') + ")\n"
            config_text += f"📍 " + self.get_text('come_trovare_l_id') + ": " + self.get_text('aggiungi_userinfobot_al_canale_e_scrivi_id')
        
        self.user_states[user_id] = {
            'action': 'configuring_channel',
            'chat_id': chat_id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_channel_config")
        keyboard.add(cancel_btn)
        
        self.bot.send_message(
            chat_id, 
            config_text, 
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def show_channel_configuration_with_error(self, chat_id: int, user_id: int, error_message: str):
        """Mostra il messaggio di configurazione canale con errore integrato"""
        config = self.db.get_channel_config()
        
        if config:
            channel_link, channel_id, is_active, created_by = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_approvazione') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('errore') + ":</b> " + error_message + "\n\n"
            config_text += f"🆔 " + self.get_text('id_attuale') + ": <code>" + channel_link + "</code>\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_id_del_canale_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"📢 <b>" + self.get_text('configurazione_canale_approvazione') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('errore') + ":</b> " + error_message + "\n\n"
            config_text += f"❌ " + self.get_text('nessun_canale_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_nuovo_id_del_canale_per_aggiornare_la_configurazione') + "\n\n"
            config_text += f"⚠️ <b>" + self.get_text('importante') + ":</b> " + self.get_text('il_bot_deve_essere_già_amministratore_nel_canale') + "!\n\n"
            config_text += f"💡 " + self.get_text('formato_esempio') + ": <code>-1001234567890</code> (" + self.get_text('id_numerico_del_canale_privato') + ")\n"
            config_text += f"📍 " + self.get_text('come_trovare_l_id') + ": " + self.get_text('aggiungi_userinfobot_al_canale_e_scrivi_id')
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_channel_config")
        keyboard.add(cancel_btn)
        
        self.bot.send_message(
            chat_id, 
            config_text, 
            parse_mode='HTML',
            reply_markup=keyboard
        )

    def handle_channel_configuration_input(self, message):
        """Gestisce l'input per la configurazione del canale"""
        user_id = message.from_user.id
        
        # Non serve più controllo /annulla, ora c'è il bottone
        
        channel_id = message.text.strip()
        
        # Valida che sia un ID numerico valido per canali/gruppi
        if not channel_id.startswith('-') or not channel_id[1:].isdigit():
            # Rimostra il messaggio di configurazione con errore
            error_msg = self.get_text('l_id_del_canale_deve_essere_un_numero_negativo_che_inizia_con') + " `-`. " + self.get_text('formato_corretto') + ": `-1001234567890`"
            self.show_channel_configuration_with_error(message.chat.id, user_id, error_msg)
            return
        
        # Salva configurazione con l'ID del canale
        success = self.db.update_channel_config(
            channel_link=channel_id,
            is_active=True,
            created_by=user_id
        )
        
        if success:
            self.bot.reply_to(
                message,
                f"✅ *" + self.get_text('canale_configurato_con_successo') + "!*\n\n"
                f"🆔 " + self.get_text('id_canale') + ": `{channel_id}`\n\n"
                f"💡 " + self.get_text('il_bot_invierà_ora_i_messaggi_di_approvazione_in_questo_canale_quando_rileva_nuovi_sconti') + ".",
                parse_mode='Markdown'
            )
            
            self.db.log_interaction(user_id, 'configure_channel', f'Canale ID: {channel_id}')
            logger.info(f"Channel configured by user {user_id}: {channel_id}")
        else:
            self.bot.reply_to(
                message,
                "❌ *" + self.get_text('errore_nel_salvataggio') + "*\n\n" + self.get_text('si_è_verificato_un_errore_riprova') + ".",
                parse_mode='Markdown'
            )
        
        # Rimuovi stato utente
        del self.user_states[user_id]
    
    # Metodi per gestire il prompt personalizzato OpenAI
    def start_prompt_configuration(self, chat_id: int, user_id: int):
        """Inizia il processo di configurazione prompt OpenAI"""
        config = self.db.get_openai_prompt_config()
        
        if config:
            prompt_text, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_openai') + "</b>\n\n"
            config_text += f"📝 " + self.get_text('prompt_attuale') + ":\n<code>" + prompt_text[:200] + ("..." if len(prompt_text) > 200 else "") + "</code>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_prompt_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_openai') + "</b>\n\n"
            config_text += f"❌ " + self.get_text('nessun_prompt_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_prompt_personalizzato_che_openai_userà_per_migliorare_i_messaggi_degli_sconti') + ".\n\n"
            config_text += f"💡 " + self.get_text('esempio') + ": 'Riscrivi questo messaggio di sconto in modo più accattivante e persuasivo, mantenendo tutte le informazioni tecniche.'"
        
        self.user_states[user_id] = {
            'action': 'configuring_prompt',
            'chat_id': chat_id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_prompt_config")
        keyboard.add(cancel_btn)
        
        self.bot.send_message(
            chat_id, 
            config_text, 
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def show_prompt_configuration_with_error(self, chat_id: int, user_id: int, error_message: str):
        """Mostra il messaggio di configurazione prompt con errore integrato"""
        config = self.db.get_openai_prompt_config()
        
        if config:
            prompt_text, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_openai') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('errore') + ":</b> " + error_message + "\n\n"
            config_text += f"📝 " + self.get_text('prompt_attuale') + ":\n<code>" + prompt_text[:200] + ("..." if len(prompt_text) > 200 else "") + "</code>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_prompt_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_openai') + "</b>\n\n"
            config_text += f"❌ <b>" + self.get_text('errore') + ":</b> " + error_message + "\n\n"
            config_text += f"❌ " + self.get_text('nessun_prompt_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('il_prompt_personalizzato_verrà_usato_da_openai_per_migliorare_i_messaggi_degli_sconti') + ".\n\n"
            config_text += f"💡 " + self.get_text('usa_il_pulsante_qui_sotto_per_configurare') + "."
            config_text += f"💡 " + self.get_text('esempio') + ": '" + self.get_text('esempio_prompt') + "'."
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_prompt_config")
        keyboard.add(cancel_btn)
        
        self.bot.send_message(
            chat_id, 
            config_text, 
            parse_mode='HTML',
            reply_markup=keyboard
        )

    def handle_prompt_configuration_input(self, message):
        """Gestisce l'input per la configurazione del prompt"""
        user_id = message.from_user.id
        
        # Non serve più controllo /annulla, ora c'è il bottone
        
        prompt_text = message.text.strip()
        
        # Valida che non sia vuoto
        if not prompt_text:
            # Rimostra il messaggio di configurazione con errore
            self.show_prompt_configuration_with_error(message.chat.id, user_id, 
                                                    self.get_text('il_prompt_non_può_essere_vuoto'))
            return
        
        # Salva configurazione con il prompt
        success = self.db.update_openai_prompt_config(prompt_text, user_id)
        
        if success:
            self.bot.reply_to(
                message,
                f"✅ *" + self.get_text('prompt_configurato_con_successo') + "!*\n\n"
                f"📝 " + self.get_text('prompt_salvato') + ": `" + prompt_text[:200] + "'...' if len(prompt_text) > 200 else ''`\n\n"
                f"💡 " + self.get_text('openai_userà_ora_questo_prompt_per_migliorare_i_messaggi_degli_sconti') + ".",
                parse_mode='Markdown'
            )
            
            self.db.log_interaction(user_id, 'configure_prompt', f"{self.get_text('prompt')}: {prompt_text[:50]}...")
            logger.info(f"{self.get_text('prompt_openai_configurato_da_utente')} {user_id}")
        else:
            self.bot.reply_to(
                message,
                "❌ *" + self.get_text('errore_nel_salvataggio') + "*\n\n" + self.get_text('si_è_verificato_un_errore_riprova') + ".",
                parse_mode='Markdown'
            )
        
        # Rimuovi stato utente
        del self.user_states[user_id]
    
    # Metodi per gestire lo slug Amazon affiliazione
    def start_amazon_affiliate_configuration(self, chat_id: int, user_id: int):
        """Inizia il processo di configurazione slug Amazon"""
        config = self.db.get_amazon_affiliate_config()
        
        if config:
            affiliate_tag, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"🏷 " + self.get_text('tag_attuale') + ": <code>" + self.escape_html(affiliate_tag) + "</code>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_tag_di_affiliazione_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"❌ " + self.get_text('nessun_tag_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_tag_di_affiliazione_amazon_che_verrà_aggiunto_ai_link_dei_prodotti') + ".\n\n"
            config_text += f"💡 " + self.get_text('esempio') + ": <code>" + self.get_text('miotag-21') + "</code> (" + self.get_text('il_tuo_tag_affiliazione_amazon') + ")\n"
            config_text += f"🔗 " + self.get_text('i_link_diventeranno') + ": amazon.it/" + self.get_text('prodotto_minuscolo') + "?tag=" + self.get_text('miotag-21')
        
        self.user_states[user_id] = {
            'action': 'configuring_amazon_affiliate',
            'chat_id': chat_id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_amazon_config")
        keyboard.add(cancel_btn)
        
        self.bot.send_message(
            chat_id, 
            config_text, 
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def start_amazon_affiliate_configuration_edit(self, call):
        """Inizia il processo di configurazione slug Amazon (edit message)"""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        
        config = self.db.get_amazon_affiliate_config()
        
        if config:
            affiliate_tag, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"🏷 " + self.get_text('tag_attuale') + ": <code>" + self.escape_html(affiliate_tag) + "</code>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_tag_di_affiliazione_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"🔗 <b>" + self.get_text('configurazione_tag_affiliazione_amazon') + "</b>\n\n"
            config_text += f"❌ " + self.get_text('nessun_tag_configurato') + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_tag_di_affiliazione_amazon_che_verrà_aggiunto_ai_link_dei_prodotti') + ".\n\n"
            config_text += f"💡 " + self.get_text('esempio') + ": <code>" + self.get_text('miotag-21') + "</code> (" + self.get_text('il_tuo_tag_affiliazione_amazon') + ")\n"
            config_text += f"🔗 " + self.get_text('i_link_diventeranno') + ": amazon.it/" + self.get_text('prodotto_minuscolo') + "?tag=" + self.get_text('miotag-21')
        
        self.user_states[user_id] = {
            'action': 'configuring_amazon_affiliate',
            'chat_id': chat_id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_amazon_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                chat_id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error modifying Amazon configuration message: {e}")
    
    def handle_amazon_affiliate_configuration_input(self, message):
        """Gestisce l'input per la configurazione del tag affiliazione"""
        user_id = message.from_user.id
        
        # Non serve più controllo /annulla, ora c'è il bottone
        
        affiliate_tag = message.text.strip()
        
        # Valida che non sia vuoto e sia un formato ragionevole
        if not affiliate_tag or len(affiliate_tag) < 3:
            self.bot.reply_to(
                message,
                f"❌ *" + self.get_text('tag_non_valido') + "*\n\n"
                f"{self.get_text('il_tag_di_affiliazione_deve_essere_almeno_di_3_caratteri')}.\n\n"
                "💡 " + self.get_text('esempio') + ": `" + self.get_text('miotag-21') + "`\n\n"
                f"{self.get_text('riprova_con_un_tag_valido_o_invia_annulla_per_annullare')}.",
                parse_mode='Markdown'
            )
            return
        
        # Salva configurazione con il tag
        success = self.db.update_amazon_affiliate_config(affiliate_tag, user_id)
        
        if success:
            # Keyboard per tornare al menu principale
            keyboard = types.InlineKeyboardMarkup()
            main_menu_btn = types.InlineKeyboardButton(
                self.get_text('main_menu'), 
                callback_data="back_to_main_menu"
            )
            keyboard.add(main_menu_btn)
            
            self.bot.reply_to(
                message,
                f"✅ *" + self.get_text('tag_affiliazione_configurato_con_successo') + "!*\n\n"
                f"🏷 " + self.get_text('tag_salvato') + ": `" + affiliate_tag + "`\n\n"
                f"💡 " + self.get_text('tutti_i_link_amazon_nei_messaggi_del_canale_avranno_ora_il_tuo_tag_di_affiliazione') + ".",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
            self.db.log_interaction(user_id, 'configure_amazon_affiliate', f'Tag: {affiliate_tag}')
            logger.info(f"Amazon affiliate tag configured by user {user_id}: {affiliate_tag}")
        else:
            self.bot.reply_to(
                message,
                "❌ *" + self.get_text('errore_nel_salvataggio') + "*\n\n" + self.get_text('si_è_verificato_un_errore_riprova') + ".",
                parse_mode='Markdown'
            )
        
        # Rimuovi stato utente
        del self.user_states[user_id]
    
    def add_affiliate_tag_to_url(self, amazon_url: str) -> str:
        """Aggiunge il tag di affiliazione all'URL Amazon"""
        config = self.db.get_amazon_affiliate_config()
        if not config:
            return amazon_url
        
        affiliate_tag, is_active, _, _, _ = config
        if not is_active or not affiliate_tag:
            return amazon_url
        
        # Se l'URL ha già parametri, aggiungi il tag con &
        if '?' in amazon_url:
            return f"{amazon_url}&tag={affiliate_tag}"
        else:
            return f"{amazon_url}?tag={affiliate_tag}"
    
    # Metodi per gestire la gestione admin
    def show_admin_management_edit(self, call):
        """Mostra la gestione admin (edit message)"""
        user_id = call.from_user.id
        
        # Solo i God Admin possono gestire altri admin
        if not self.is_god_admin(user_id):
            unauthorized_text = "❌ <b>" + self.get_text('accesso_negato') + "</b>\n\n"
            unauthorized_text += "🔒 " + self.get_text('solo_i_god_admin_possono_gestire_altri_amministratori') + ".\n\n"
            unauthorized_text += "👤 " + self.get_text('il_tuo_livello') + ": <b>" + self.get_text('regular_admin') + "</b>"
            
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard.add(back_btn)
            
            try:
                self.bot.edit_message_text(
                    unauthorized_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                try:
                    self.bot.edit_message_caption(
                        call.message.chat.id,
                        call.message.message_id,
                        caption=unauthorized_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    self.bot.send_message(
                        call.message.chat.id,
                        unauthorized_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('accesso_negato'))
            return
        
        # Ottieni lista admin
        admin_users = self.db.get_all_admin_users()
        god_admin_count = len(self.authorized_users)
        
        admin_text = "👥 <b>" + self.get_text('gestione_amministratori') + "</b>\n\n"
        admin_text += "🔐 <b>" + self.get_text('importante') + ":</b> " + self.get_text('solo_i_god_admin_possono_gestire_altri_amministratori') + ".\n\n"
        admin_text += f"⚡️ <b>" + self.get_text('god_admin') + ":</b> " + str(god_admin_count) + " " + self.get_text('utenti_definiti_nel_file_env') + "\n"
        admin_text += f"👤 <b>" + self.get_text('regular_admin') + ":</b> " + str(len(admin_users)) + " " + self.get_text('utenti_aggiunti_dinamicamente') + "\n\n"
        
        if admin_users:
            admin_text += "<b>📋 " + self.get_text('lista_regular_admin') + ":</b>\n"
        else:
            admin_text += "📋 <b>" + self.get_text('nessun_regular_admin_presente') + "</b>\n\n"
            admin_text += self.get_text('usa_il_pulsante_qui_sotto_per_aggiungere_il_primo_amministratore') + "."
        
        # Keyboard con admin e azioni
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        # Lista admin con pulsanti rimuovi
        for admin_user_id, username, first_name, last_name, is_active, added_by, created_at in admin_users:
            # Usa solo l'ID per il display
            display_id = str(admin_user_id)
            
            # Bottone info admin con possibilità di rimuovere
            remove_btn = types.InlineKeyboardButton(
                f"🗑 Rimuovi: {display_id}",
                callback_data=f"remove_admin_{admin_user_id}"
            )
            keyboard.add(remove_btn)
        
        # Bottone aggiungi admin
        add_btn = types.InlineKeyboardButton(
            f"➕ " + self.get_text('aggiungi_nuovo_admin'), 
            callback_data="add_admin_user"
        )
        keyboard.add(add_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                admin_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=admin_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    admin_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "👥 " + self.get_text('gestione_admin'))
    
    def start_add_admin_process_edit(self, call, user_id: int):
        """Inizia il processo di aggiunta admin (edit message)"""
        # Solo God Admin possono aggiungere admin
        if not self.is_god_admin(user_id):
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('solo_god_admin_possono_aggiungere_admin'))
            return
        
        self.user_states[user_id] = {
            'action': 'adding_admin',
            'chat_id': call.message.chat.id
        }
        
        add_admin_text = "➕ <b>" + self.get_text('aggiungi_nuovo_amministratore') + "</b>\n\n"
        add_admin_text += "👤 " + self.get_text('invia_l_id_numerico_dell_utente_da_rendere_amministratore') + ".\n\n"
        add_admin_text += "💡 <b>" + self.get_text('come_trovare_l_id') + ":</b>\n"
        add_admin_text += "• " + self.get_text('l_utente_può_scrivere_a_userinfobot_e_inviare_start') + "\n"
        add_admin_text += "• " + self.get_text('oppure_usare_rawdatabot_per_ottenere_l_id') + "\n\n"
        add_admin_text += "📝 <b>" + self.get_text('esempio_id') + ":</b> <code>123456789</code>\n\n"
        add_admin_text += "⚠️ <b>" + self.get_text('nota') + ":</b> " + self.get_text('i_regular_admin_potranno_usare_il_bot_ma_non_potranno_aggiungere_altri_amministratori') + "."
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_admin_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                add_admin_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=add_admin_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    add_admin_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        
        self.bot.answer_callback_query(call.id, "➕ " + self.get_text('aggiungi_admin'))
    
    def handle_add_admin_input(self, message):
        """Gestisce l'input per aggiungere un nuovo admin"""
        user_id = message.from_user.id
        
        # Non serve più controllo /annulla, ora c'è il bottone
        
        admin_id_input = message.text.strip()
        
        # Valida che sia un numero
        try:
            new_admin_id = int(admin_id_input)
        except ValueError:
            self.bot.reply_to(
                message,
                f"❌ <b>" + self.get_text('id_non_valido') + "</b>\n\n" +
                 self.get_text('l_id_deve_essere_un_numero_intero') + ".\n\n" +
                f"💡 " + self.get_text('esempio') + ": <code>123456789</code>\n\n" +
                f"{self.get_text('riprova_con_un_id_valido')}:",
                parse_mode='HTML'
            )
            return
        
        # Controlla che non sia già autorizzato
        if self.is_user_authorized(new_admin_id):
            error_text = "⚠️ <b>" + self.get_text('utente_già_autorizzato') + "</b>\n\n"
            if self.is_god_admin(new_admin_id):
                error_text += f"👤 " + self.get_text('l_utente') + " <code>" + str(new_admin_id) + "</code> " + self.get_text('è_già_un') + " <b>" + self.get_text('god_admin') + "</b> " + self.get_text('definito_nel_file_env') + "."
            else:
                error_text += f"👤 {self.get_text('l_utente')} <code>" + str(new_admin_id) + "</code> {self.get_text('è_già_un')} <b>{self.get_text('regular_admin')}</b>."
            
            # Keyboard con bottone per tornare alla gestione admin
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_alla_gestione_admin'), callback_data="show_admin_management")
            keyboard.add(back_btn)
            
            self.bot.reply_to(
                message,
                error_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
            # Rimuovi stato utente
            del self.user_states[user_id]
            return
        
        # Prova ad aggiungere l'admin (usando solo l'ID)
        success = self.db.add_admin_user(
            user_id=new_admin_id,
            added_by=user_id
        )
        
        if success:
            success_text = f"✅ <b>{self.get_text('amministratore_aggiunto_con_successo')}!</b>\n\n"
            success_text += f"👤 <b>" + self.get_text('nuovo_admin_id') + ":</b> <code>" + str(new_admin_id) + "</code>\n"
            success_text += f"🔑 <b>" + self.get_text('livello') + ":</b> " + self.get_text('regular_admin') + "\n"
            success_text += f"⚡️ <b>" + self.get_text('aggiunto_da') + ":</b> <code>" + str(user_id) + "</code>\n\n"
            success_text += f"💡 " + self.get_text('l_utente') + " <code>" + str(new_admin_id) + "</code> " + self.get_text('può_ora_utilizzare_il_bot_ma_non_può_aggiungere_altri_amministratori') + "."
            
            # Keyboard con bottone per tornare alla gestione admin
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_alla_gestione_admin'), callback_data="show_admin_management")
            keyboard.add(back_btn)
            
            self.bot.reply_to(
                message,
                success_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
            self.db.log_interaction(user_id, 'add_admin', f"{self.get_text('nuovo_admin')}: {new_admin_id}")
            logger.info(f"{self.get_text('nuovo_admin')} {new_admin_id} {self.get_text('aggiunto_da')} {self.get_text('god_admin')} {user_id}")
        else:
            self.bot.reply_to(
                message,
                "❌ <b>" + self.get_text('errore_nell_aggiunta') + "</b>\n\n" + self.get_text('si_è_verificato_un_errore_riprova') + ".",
                parse_mode='HTML'
            )
        
        # Rimuovi stato utente
        del self.user_states[user_id]
    
    def confirm_remove_admin(self, call, admin_user_id: int):
        """Mostra conferma rimozione admin"""
        admin_info = self.db.get_admin_user_info(admin_user_id)
        if not admin_info:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('admin_non_trovato'))
            return
        
        user_id, username, first_name, last_name, is_active, added_by, created_at = admin_info
        
        # Prepara nome display
        display_name = first_name or "N/A"
        if username:
            display_name += f" (@{username})"
        
        confirm_text = f"🗑 <b>" + self.get_text('conferma_rimozione_amministratore') + "</b>\n\n"
        confirm_text += f"🆔 <b>" + self.get_text('id') + ":</b> <code>" + str(admin_user_id) + "</code>\n"
        confirm_text += f"📅 <b>" + self.get_text('aggiunto_il') + ":</b> " + created_at[:16] + "\n"
        confirm_text += f"👥 <b>" + self.get_text('aggiunto_da') + ":</b> <code>" + str(added_by) + "</code>\n\n"
        confirm_text += "⚠️ <b>" + self.get_text('questa_azione_non_può_essere_annullata') + "</b>\n"
        confirm_text += self.get_text('l_utente_non_potrà_più_utilizzare_il_bot') + "."
        
        keyboard = types.InlineKeyboardMarkup()
        confirm_btn = types.InlineKeyboardButton(
            f"✅ " + self.get_text('conferma_rimozione'), 
            callback_data=f"confirm_remove_admin_{admin_user_id}"
        )
        cancel_btn = types.InlineKeyboardButton(
            f"❌ " + self.get_text('annulla'),
            callback_data="cancel_remove_admin"
        )
        keyboard.add(confirm_btn)
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                confirm_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=confirm_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    confirm_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "⚠️ " + self.get_text('conferma_rimozione'))
    
    def remove_admin_final(self, call, admin_user_id: int):
        """Rimuove definitivamente l'admin"""
        admin_info = self.db.get_admin_user_info(admin_user_id)
        if not admin_info:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('admin_non_trovato'))
            return
        
        user_id, username, first_name, last_name, is_active, added_by, created_at = admin_info
        
        # Rimuovi l'admin dal database
        success = self.db.remove_admin_user(admin_user_id)
        
        if success:
            success_text = f"✅ <b>" + self.get_text('amministratore_rimosso') + "</b>\n\n"
            success_text += f"👤 " + self.get_text('l_utente') + " <code>" + str(admin_user_id) + "</code> " + self.get_text('è_stato_rimosso_dagli_amministratori') + ".\n\n"
            success_text += f"🚫 " + self.get_text('l_utente') + " <code>" + str(admin_user_id) + "</code> " + self.get_text('non_può_più_utilizzare_il_bot') + "."
            
            # Keyboard per tornare alla gestione admin
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton(
                f"🔙 " + self.get_text('torna_alla_gestione_admin'), 
                callback_data="show_admin_management"
            )
            keyboard.add(back_btn)
            
            try:
                self.bot.edit_message_text(
                    success_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                try:
                    self.bot.edit_message_caption(
                        call.message.chat.id,
                        call.message.message_id,
                        caption=success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    self.bot.send_message(
                        call.message.chat.id,
                        success_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            
            self.db.log_interaction(call.from_user.id, 'remove_admin', f"{self.get_text('admin_rimosso')}: {admin_user_id}")
            logger.info(f"{self.get_text('admin_rimosso')} {admin_user_id} {self.get_text('rimosso_da')} {self.get_text('god_admin')} {call.from_user.id}")
            self.bot.answer_callback_query(call.id, "✅ " + self.get_text('admin_rimosso'))
        else:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_nella_rimozione'))
    
    # Metodi per gestire l'approvazione automatica
    def show_auto_approval_config_edit(self, call):
        """Mostra la configurazione approvazione automatica (edit message)"""
        config = self.db.get_auto_approval_config()
        
        if config:
            is_enabled, created_by, created_at, updated_at = config
            status_emoji = "✅" if is_enabled else "❌"
            status_text = self.get_text('abilitata') if is_enabled else self.get_text('disabilitata')
        else:
            is_enabled = False
            status_emoji = "❌"
            status_text = self.get_text('disabilitata')
            created_by = None
            created_at = None
        
        config_text = f"⚡️ <b>" + self.get_text('configurazione_approvazione_automatica') + "</b>\n\n"
        config_text += f"{status_emoji} <b>{self.get_text('stato_attuale')}:</b> {status_text}\n\n"
        
        if is_enabled:
            config_text += "🤖 <b>" + self.get_text('modalità_attiva') + ":</b> " + self.get_text('i_messaggi_degli_sconti_vengono_automaticamente_approvati_e_inviati_ai_gruppi_senza_intervento_manuale') + ".\n\n"
            config_text += "📢 <b>" + self.get_text('canale_database') + ":</b> " + self.get_text('se_configurato_i_messaggi_verranno_comunque_inviati_al_canale_database_ma_SENZA_pulsante_di_approvazione_così_avrai_sempre_l_elenco_completo_per_eventuali_ripost_futuri') + ".\n\n"
        else:
            config_text += "👤 <b>" + self.get_text('modalità_attiva') + ":</b> " + self.get_text('i_messaggi_degli_sconti_richiedono_approvazione_manuale_prima_di_essere_inviati_ai_gruppi') + ".\n\n"
            config_text += "📢 <b>" + self.get_text('canale_database') + ":</b> " + self.get_text('i_messaggi_vengono_inviati_al_canale_database_CON_pulsante_di_approvazione_per_la_revisione_manuale') + ".\n\n"
        
        config_text += "💡 <b>" + self.get_text('scegli_la_modalità_desiderata') + ":</b>"
        
        if created_at:
            config_text += f"\n\n📅 " + self.get_text('ultimo_aggiornamento') + ": " + updated_at[:16] if updated_at else created_at[:16]
            if created_by:
                config_text += f"\n👤 " + self.get_text('configurato_da') + ": <code>" + str(created_by) + "</code>"
        
        # Keyboard con radio buttons
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        # Bottone per abilitare (con indicatore radio)
        if is_enabled:
            enable_btn = types.InlineKeyboardButton(
                f"🔘 " + self.get_text('abilita_approvazione_automatica'), 
                callback_data="toggle_auto_approval_enable"
            )
        else:
            enable_btn = types.InlineKeyboardButton(
                f"⚪️ " + self.get_text('abilita_approvazione_automatica'), 
                callback_data="toggle_auto_approval_enable"
            )
        
        # Bottone per disabilitare (con indicatore radio)
        if not is_enabled:
            disable_btn = types.InlineKeyboardButton(
                f"🔘 " + self.get_text('disabilita_approvazione_automatica'), 
                callback_data="toggle_auto_approval_disable"
            )
        else:
            disable_btn = types.InlineKeyboardButton(
                f"⚪️ " + self.get_text('disabilita_approvazione_automatica'), 
                callback_data="toggle_auto_approval_disable"
            )
        
        keyboard.add(enable_btn)
        keyboard.add(disable_btn)
        
        # Bottone back al menu principale
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard.add(back_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            try:
                self.bot.edit_message_caption(
                    call.message.chat.id,
                    call.message.message_id,
                    caption=config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e2:
                self.bot.send_message(
                    call.message.chat.id,
                    config_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        self.bot.answer_callback_query(call.id, "⚡️ " + self.get_text('approvazione_automatica'))
    
    def toggle_auto_approval(self, call, enable: bool):
        """Toggle dello stato dell'approvazione automatica"""
        user_id = call.from_user.id
        
        # Salva la configurazione
        success = self.db.update_auto_approval_config(enable, user_id)
        
        if success:
            status_text = self.get_text('abilitata') if enable else self.get_text('disabilitata')
            status_emoji = "✅" if enable else "❌"
            
            # Aggiorna il menu mantenendo la stessa interfaccia
            self.show_auto_approval_config_edit(call)
            
            # Messaggio di conferma
            confirmation_message = f"{status_emoji} {self.get_text('approvazione_automatica')} {status_text}"
            self.bot.answer_callback_query(call.id, confirmation_message)
            
            # Log dell'azione
            self.db.log_interaction(user_id, 'toggle_auto_approval', f"{self.get_text('stato')}: {status_text}")
            logger.info(f"Auto approval {status_text} by user {user_id}")
        else:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_nell_aggiornamento'))
    
    def improve_message_with_openai(self, original_message: str) -> str:
        """Migliora il messaggio usando OpenAI ChatGPT-4"""
        if not self.openai_api_key:
            logger.warning("OpenAI API key not configured")
            return original_message
        
        # Ottieni il prompt personalizzato
        prompt_config = self.db.get_openai_prompt_config()
        if not prompt_config:
            logger.warning("Prompt OpenAI not configured")
            return original_message
        
        custom_prompt, is_active, _, _, _ = prompt_config
        if not is_active:
            logger.info("Prompt OpenAI disabled")
            return original_message
        
        try:
            # Import locale per evitare conflitti
            import openai
            
            # Chiamata all'API OpenAI con la sintassi più semplice
            openai.api_key = self.openai_api_key
            
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": custom_prompt},
                    {"role": "user", "content": original_message}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            improved_message = response.choices[0].message.content.strip()
            logger.info("Message improved with OpenAI")
            return improved_message
            
        except Exception as e:
            logger.error(f"Error calling OpenAI: {e}")
            return original_message
    
    def send_discount_notification(self, product_id: int, discount_id: int, product_data: Dict[str, Any]):
        """Invia notifica di sconto al canale di approvazione"""
        config = self.db.get_channel_config()
        
        if not config or not config[2]:  # is_active
            logger.warning("Approval channel not configured or inactive")
            return
        
        channel_link, channel_id, is_active, created_by = config
        
        # Converte il link nel formato corretto per l'API Telegram
        chat_id = self.convert_channel_link_to_chat_id(channel_link)
        
        try:
            # Prepara il messaggio
            title = product_data.get('title', self.get_text('prodotto_amazon'))
            image_url = product_data.get('image_url')
            amazon_url = product_data.get('amazon_url', '')
            category_name = product_data.get('category_name', self.get_text('senza_categoria'))
            discount_percentage = product_data.get('discount_percentage', 0)
            original_price = product_data.get('original_price', self.get_text('n_a'))
            discounted_price = product_data.get('discounted_price', self.get_text('n_a'))
            
            # Escape caratteri speciali per Markdown
            escaped_title = self.escape_markdown(title)
            escaped_category = self.escape_markdown(category_name)
            escaped_original = self.escape_markdown(original_price)
            escaped_discounted = self.escape_markdown(discounted_price)
            
            # Crea il messaggio originale (senza escape per OpenAI) - SENZA LINK
            original_message = f"🔥 {self.get_text('nuovo_sconto_rilevato')} 🔥\n\n"
            original_message += f"📦 {title}\n\n"
            original_message += f"📂 {self.get_text('categoria')}: {category_name}\n"
            original_message += f"💰 {self.get_text('sconto')}: -{discount_percentage}%\n"
            original_message += f"💲 {self.get_text('prezzo_originale')}: {original_price}\n"
            original_message += f"💲 {self.get_text('prezzo_scontato')}: {discounted_price}"
            
            # Migliora il messaggio con OpenAI
            improved_message = self.improve_message_with_openai(original_message)
            
            # Se OpenAI ha migliorato il messaggio, usalo con HTML
            # altrimenti usa il formato originale con escape HTML
            if improved_message != original_message:
                # OpenAI ha migliorato il messaggio, usalo così com'è (dovrebbe già essere in HTML)
                notification_text = improved_message
                use_html = True
                logger.info("Using improved message with OpenAI with HTML formatting")
            else:
                # Usa il formato originale con escape HTML
                escaped_title = self.escape_html(title)
                escaped_category = self.escape_html(category_name)
                escaped_original = self.escape_html(original_price)
                escaped_discounted = self.escape_html(discounted_price)
                
                notification_text = f"🔥 <b>" + self.get_text('nuovo_sconto_rilevato') + "</b> 🔥\n\n"
                notification_text += f"📦 <b>" + escaped_title + "</b>\n\n"
                notification_text += f"📂 " + self.get_text('categoria') + ": <b>" + escaped_category + "</b>\n"
                notification_text += f"💰 " + self.get_text('sconto') + ": <b>-" + discount_percentage + "%</b>\n"
                notification_text += f"💲 " + self.get_text('prezzo_originale') + ": <s>" + escaped_original + "</s>\n"
                notification_text += f"💲 " + self.get_text('prezzo_scontato') + ": <b>" + escaped_discounted + "</b>\n\n"
                notification_text += f"🔗 <a href='{amazon_url}'>" + self.get_text('vai_al_prodotto') + "</a>"
                use_html = True
                logger.info("Using original message with HTML formatting")
            
            # Controlla se l'approvazione automatica è abilitata
            auto_approval_config = self.db.get_auto_approval_config()
            is_auto_approval_enabled = auto_approval_config and auto_approval_config[0]  # is_enabled
            
            # Keyboard con pulsanti (varia in base all'approvazione automatica)
            keyboard = types.InlineKeyboardMarkup()
            
            # Solo se approvazione automatica è DISABILITATA, aggiungi il pulsante approva
            if not is_auto_approval_enabled:
                approve_btn = types.InlineKeyboardButton(
                    "✅ " + self.get_text('approva'), 
                    callback_data=f"approve_{product_id}_{discount_id}"
                )
                keyboard.add(approve_btn)
                logger.info("Message sent to approval channel WITH approval button (manual approval)")
            else:
                logger.info("Message sent to approval channel WITHOUT approval button (auto approval enabled)")
            
            # Aggiungi sempre il pulsante con link di affiliazione
            affiliate_url = self.add_affiliate_tag_to_url(amazon_url)
            purchase_text = self.get_purchase_button_text()
            affiliate_btn = types.InlineKeyboardButton(
                purchase_text, 
                url=affiliate_url
            )
            keyboard.add(affiliate_btn)
            
            # Invia messaggio con o senza immagine (sempre con HTML)
            if image_url:
                try:
                    sent_message = self.bot.send_photo(
                        chat_id,
                        image_url,
                        caption=notification_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Error sending photo: {e}, sending only text")
                    sent_message = self.bot.send_message(
                        chat_id,
                        notification_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            else:
                sent_message = self.bot.send_message(
                    chat_id,
                    notification_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            
            # Salva il messaggio di approvazione nel database con il messaggio migliorato
            improved_msg_to_save = notification_text if improved_message != original_message else None
            approval_message_id = self.db.add_approval_message(
                product_id=product_id,
                discount_id=discount_id,
                channel_message_id=sent_message.message_id,
                improved_message=improved_msg_to_save
            )
            
            logger.info(f"Discount notification sent to channel for product {product_id}")
            
            # Se auto approval è attivato, approva automaticamente e pubblica sul gruppo finale
            if is_auto_approval_enabled:
                try:
                    # Marca come approvato nel database (approvazione automatica)
                    if approval_message_id:
                        success = self.db.approve_message(approval_message_id, 0)  # 0 = approvazione automatica
                        if success:
                            logger.info(f"Message approved automatically for product {product_id}")
                            
                            # Ottieni i dati del prodotto per la pubblicazione
                            product = self.db.get_product_by_id(product_id)
                            discount = self.db.get_latest_discount_for_product(product_id)
                            
                            if product and discount:
                                # Pubblica automaticamente sul gruppo finale
                                self.send_approved_message_to_group(product, discount, improved_msg_to_save)
                                logger.info(f"✅ Message published automatically on group for product {product_id}")
                            else:
                                logger.error(f"Unable to obtain product/discount data for automatic publication: {product_id}")
                        else:
                            logger.error(f"Error in automatic approval for product {product_id}")
                except Exception as auto_approval_error:
                    logger.error(f"Error in automatic publication for product {product_id}: {auto_approval_error}")
            
        except Exception as e:
            logger.error(f"Error sending notification to channel: {e}")
    
    def approve_discount_notification(self, call, approval_data: str):
        """Gestisce l'approvazione di una notifica sconto"""
        try:
            # Parse dei dati dal callback
            parts = approval_data.split('_')
            product_id = int(parts[0])
            discount_id = int(parts[1])
            
            # Ottieni dati dal database
            approval = self.db.get_approval_by_message_id(call.message.message_id)
            if not approval:
                self.bot.answer_callback_query(call.id, "❌ " + self.get_text('messaggio_non_trovato'))
                return
            
            approval_id, db_product_id, db_discount_id, is_approved, improved_message = approval
            
            if is_approved:
                # Aggiorna il pulsante se non è già stato fatto
                approved_text = f"✅ <b>" + self.get_text('approvato') + "</b>\n\n"
                original_text = call.message.caption or call.message.text or ""
                if not original_text.startswith("✅"):
                    approved_text += original_text
                else:
                    approved_text = original_text  # È già stato formattato
                
                # Crea keyboard mantenendo la struttura originale ma con pulsante approvato
                keyboard = types.InlineKeyboardMarkup()
                approved_btn = types.InlineKeyboardButton("✅ " + self.get_text('già_approvato'), callback_data="already_approved")
                
                # Mantieni il pulsante Amazon (prendi l'URL dal pulsante originale se esiste)
                original_keyboard = call.message.reply_markup
                amazon_url = None
                if original_keyboard and original_keyboard.keyboard:
                    for row in original_keyboard.keyboard:
                        for button in row:
                            if button.url and "amazon" in button.url.lower():
                                amazon_url = button.url
                                break
                
                keyboard.add(approved_btn)
                
                # Aggiungi il pulsante Amazon se esisteva
                if amazon_url:
                    purchase_text = self.get_purchase_button_text()
                    amazon_btn = types.InlineKeyboardButton(purchase_text, url=amazon_url)
                    keyboard.add(amazon_btn)
                
                try:
                    if call.message.caption:
                        self.bot.edit_message_caption(
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            caption=approved_text,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    else:
                        self.bot.edit_message_text(
                            text=approved_text,
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                except Exception as e:
                    pass  # Se c'è un errore, continua comunque
                
                self.bot.answer_callback_query(call.id, "✅ " + self.get_text('già_approvato'))
                return
            
            # Approva il messaggio
            success = self.db.approve_message(approval_id, call.from_user.id)
            
            if success:
                # Ottieni dettagli prodotto
                product = self.db.get_product_by_id(product_id)
                if not product:
                    self.bot.answer_callback_query(call.id, "❌ " + self.get_text('prodotto_non_trovato'))
                    return
                
                product_id_db, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product
                
                # Ottieni dettagli sconto
                discount = self.db.get_latest_discount_for_product(product_id)
                if not discount:
                    self.bot.answer_callback_query(call.id, "❌ " + self.get_text('sconto_non_trovato'))
                    return
                
                discount_percentage, original_price, discounted_price, currency, detected_at = discount
                
                # Invia messaggio approvato al gruppo della categoria
                self.send_approved_message_to_group(product, discount, improved_message)
                
                # Aggiorna il messaggio nel canale
                approved_text = f"✅ <b>" + self.get_text('approvato_da') + " " + call.from_user.first_name + "</b>\n\n"
                original_text = call.message.caption or call.message.text or ""
                approved_text += original_text
                
                # Crea keyboard mantenendo la struttura originale ma con pulsante approvato
                keyboard = types.InlineKeyboardMarkup()
                approved_btn = types.InlineKeyboardButton("✅ " + self.get_text('già_approvato'), callback_data="already_approved")
                
                # Mantieni il pulsante Amazon (prendi l'URL dal pulsante originale se esiste)
                original_keyboard = call.message.reply_markup
                amazon_url = None
                if original_keyboard and original_keyboard.keyboard:
                    for row in original_keyboard.keyboard:
                        for button in row:
                            if button.url and "amazon" in button.url.lower():
                                amazon_url = button.url
                                break
                
                keyboard.add(approved_btn)
                
                # Aggiungi il pulsante Amazon se esisteva
                if amazon_url:
                    purchase_text = self.get_purchase_button_text()
                    amazon_btn = types.InlineKeyboardButton(purchase_text, url=amazon_url)
                    keyboard.add(amazon_btn)
                
                try:
                    logger.info(f"Updating message in approval channel - ID: {call.message.message_id}")
                    # Prova prima a modificare il caption (se è una foto)
                    if call.message.caption:
                        logger.info("Updating caption of message with photo")
                        self.bot.edit_message_caption(
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            caption=approved_text,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    else:
                        # Altrimenti modifica il testo del messaggio
                        logger.info("Updating text of message")
                        self.bot.edit_message_text(
                            text=approved_text,
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    logger.info("Message in approval channel updated successfully")
                except Exception as edit_error:
                    logger.error(f"Error in editing message in approval channel: {edit_error}")
                    # Continua comunque con l'approvazione
                
                self.bot.answer_callback_query(call.id, "✅ " + self.get_text('messaggio_approvato_e_inviato_al_gruppo') + "!")
                
                self.db.log_interaction(call.from_user.id, 'approve_discount', f'Prodotto: {product_id}')
                logger.info(f"Discount approved by user {call.from_user.id} for product {product_id}")
            else:
                self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_nell_approvazione'))
                
        except Exception as e:
            logger.error(f"Error in approval: {e}")
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_interno'))
    
    def send_approved_message_to_group(self, product_data: tuple, discount_data: tuple, improved_message: str = None):
        """Invia il messaggio approvato al gruppo della categoria"""
        try:
            product_id_db, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product_data
            discount_percentage, original_price, discounted_price, currency, detected_at = discount_data
            
            # Ottieni il link del gruppo per questa categoria
            category = self.db.get_category_by_id(category_id)
            if not category:
                logger.error(f"Category {category_id} not found")
                return
            
            cat_id, name, description, telegram_link, created_by_cat, created_at_cat = category
            
            if not telegram_link:
                logger.warning(f"No Telegram link configured for category {name}")
                return
            
            # Converte il link nel formato corretto per l'API Telegram
            group_chat_id = self.convert_channel_link_to_chat_id(telegram_link)
            
            # Usa il messaggio migliorato dall'AI se disponibile, altrimenti crea uno standard
            if improved_message:
                # Usa il messaggio migliorato dall'AI
                group_text = improved_message
                
                # Rimuovi eventuali link testuali dall'AI (per evitare placeholder)
                # Rimuovi pattern come "🔗 Link prodotto: [url]" o simili
                group_text = re.sub(r'🔗\s*[Ll]ink\s+prodotto\s*:\s*\S+', '', group_text)
                group_text = re.sub(r'🔗\s*[Ll]ink\s*:\s*\S+', '', group_text)
                group_text = re.sub(r'\n\n\n+', '\n\n', group_text)  # Rimuovi righe vuote extra
                group_text = group_text.strip()
                
                use_html = True  # I messaggi AI usano formattazione HTML
                logger.info("Using improved message with AI for group")
            else:
                # Fallback: crea messaggio standard con escape HTML
                escaped_title = self.escape_html(title)
                escaped_original = self.escape_html(original_price)
                escaped_discounted = self.escape_html(discounted_price)
                
                group_text = f"🔥 <b>OFFERTA SPECIALE</b> 🔥\n\n"
                group_text += f"📦 <b>{escaped_title}</b>\n\n"
                group_text += f"💰 " + self.get_text('sconto') + ": <b>-{discount_percentage}%</b>\n"
                group_text += f"💲 " + self.get_text('prezzo_originale') + ": <s>{escaped_original}</s>\n"
                group_text += f"💲 " + self.get_text('prezzo_scontato') + ": <b>{escaped_discounted}</b>\n\n"
                group_text += f"⚡️ <i>" + self.get_text('offerta_limitata_nel_tempo') + "</i>"
                
                use_html = True
                logger.info("Using standard message with HTML formatting for group")
            
            # Crea keyboard con bottone "Acquista su Amazon" (come nel canale DB)
            keyboard = types.InlineKeyboardMarkup()
            affiliate_url = self.add_affiliate_tag_to_url(amazon_url)
            purchase_text = self.get_purchase_button_text()
            affiliate_btn = types.InlineKeyboardButton(
                purchase_text, 
                url=affiliate_url
            )
            keyboard.add(affiliate_btn)
            
            # Invia al gruppo della categoria CON IL BOTTONE (sempre con HTML)
            if image_url:
                try:
                    self.bot.send_photo(
                        group_chat_id,
                        image_url,
                        caption=group_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Error sending photo to group: {e}, sending only text")
                    self.bot.send_message(
                        group_chat_id,
                        group_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
            else:
                self.bot.send_message(
                    group_chat_id,
                    group_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            
            logger.info(f"Message approved sent to group {telegram_link} for product {product_id_db}")
            
        except Exception as e:
            logger.error(f"Error sending message to group: {e}")
    
    def show_test_categories(self, call):
        """Mostra categorie per test prompt"""
        categories = self.db.get_all_categories()
        
        if not categories:
            self.bot.edit_message_text(
                f"❌ <b>" + self.get_text('nessuna_categoria_disponibile') + "</b>\n\n" +
                f"{self.get_text('crea_prima_delle_categorie_per_testare_il_prompt')}.", 
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('nessuna_categoria'))
            return
        
        test_text = f"🧪 <b>" + self.get_text('test_prompt_ai') + "</b>\n\n"
        test_text += f"📂 <b>" + self.get_text('seleziona_una_categoria') + ":</b>"
        
        # Crea keyboard con le categorie
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for cat_id, name, description, telegram_link, created_by, created_at in categories:
            button_text = f"📂 {name}"
            callback_data = f"test_category_{cat_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
        
        # Bottone annulla
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_test_prompt")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                test_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            self.bot.send_message(
                call.message.chat.id,
                test_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        
        self.bot.answer_callback_query(call.id, "🧪 " + self.get_text('scegli_categoria'))
    
    def show_test_products(self, call, category_id: int):
        """Mostra prodotti della categoria per test prompt"""
        category = self.db.get_category_by_id(category_id)
        if not category:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('categoria_non_trovata'))
            return
        
        products = self.db.get_products_by_category(category_id)
        
        if not products:
            test_text = f"🧪 <b>" + self.get_text('test_prompt_ai') + "</b>\n\n"
            test_text += f"📂 " + self.get_text('categoria') + ": <b>{category[1]}</b>\n\n"
            test_text += f"❌ <b>" + self.get_text('nessun_prodotto_disponibile') + "</b>\n\n"
            test_text += f"{self.get_text('aggiungi_prima_dei_prodotti_a_questa_categoria')}."
            
            keyboard = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_alle_categorie'), callback_data="test_prompt")
            cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_test_prompt")
            keyboard.add(back_btn)
            keyboard.add(cancel_btn)
            
            try:
                self.bot.edit_message_text(
                    test_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                self.bot.send_message(
                    call.message.chat.id,
                    test_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('nessun_prodotto'))
            return
        
        test_text = f"🧪 <b>" + {self.get_text('test_prompt_ai')} + "</b>\n\n"
        test_text += f"📂 " + self.get_text('categoria') + ": <b>{category[1]}</b>\n\n"
        test_text += f"🛒 <b>" + self.get_text('seleziona_un_prodotto') + ":</b>"
        
        # Crea keyboard con i prodotti
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for product_id, amazon_url, title, added_by, created_at in products:
            product_title = title if title else f"{self.get_text('prodotto')} " + {product_id}
            button_text = f"🛒 {product_title[:50]}{'...' if len(product_title) > 50 else ''}"
            callback_data = f"test_product_{product_id}"
            button = types.InlineKeyboardButton(button_text, callback_data=callback_data)
            keyboard.add(button)
            
        # Bottoni navigazione
        back_btn = types.InlineKeyboardButton("🔙 " + self.get_text('torna_alle_categorie'), callback_data="test_prompt")
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_test_prompt")
        keyboard.add(back_btn)
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                test_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            self.bot.send_message(
                call.message.chat.id,
                test_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        
        self.bot.answer_callback_query(call.id, "🛒 " + self.get_text('scegli_prodotto'))
    
    def execute_prompt_test(self, call, product_id: int):
        """Esegue il test del prompt su un prodotto specifico"""
        import random
        
        # Ottieni dati prodotto
        product = self.db.get_product_by_id(product_id)
        if not product:
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('prodotto_non_trovato'))
            return
        
        product_id_db, amazon_url, title, image_url, category_id, added_by, created_at, category_name = product
        
        # Mostra messaggio di caricamento
        loading_text = f"🧪 <b>" + self.get_text('esecuzione_test_prompt_ai') + "</b>\n\n"
        loading_text += f"⏳ " + self.get_text('sto_testando_il_prompt_su') + ":\n"
        loading_text += f"📦 <b>" + self.escape_html(title or self.get_text('prodotto_amazon')) + "</b>\n\n"
        loading_text += f"🔄 " + self.get_text('generazione_dati_di_test_e_chiamata_openai') + "..."
        
        try:
            self.bot.edit_message_text(
                loading_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML'
            )
        except Exception as e:
            self.bot.send_message(
                call.message.chat.id,
                loading_text,
                parse_mode='HTML'
            )
        
        self.bot.answer_callback_query(call.id, "🧪 " + self.get_text('test_in_corso') + "...")
        
        # Tenta di fare scraping reale, se fallisce usa dati fittizi
        try:
            scrape_data = self.scrape_amazon_product(amazon_url)
            if scrape_data.get('has_discount', False):
                # Usa dati reali
                discount_percentage = scrape_data['discount_percentage']
                original_price = scrape_data['original_price']
                discounted_price = scrape_data['discounted_price']
                test_data_source = "🔍 " + self.get_text('dati_reali_da_amazon')
            else:
                # Usa dati fittizi
                raise Exception(self.get_text('nessuno_sconto_reale_trovato'))
        except:
            # Genera dati fittizi per il test
            discount_percentage = random.randint(10, 50)
            original_price_value = random.randint(50, 500)
            discounted_price_value = round(original_price_value * (1 - discount_percentage / 100), 2)
            original_price = f"{original_price_value:.2f}€".replace('.', ',')
            discounted_price = f"{discounted_price_value:.2f}€".replace('.', ',')
            test_data_source = "🎲 " + self.get_text('dati_fittizi_per_test')
        
        # Crea il messaggio originale (stesso formato del cronjob)
        original_message = f"🔥 " + self.get_text('nuovo_sconto_rilevato') + " 🔥\n\n"
        original_message += f"📦 " + title or self.get_text('prodotto_amazon') + "\n\n"
        original_message += f"📂 " + self.get_text('categoria') + ": " + category_name or self.get_text('senza_categoria') + "\n"
        original_message += f"💰 " + self.get_text('sconto') + ": -{discount_percentage}%\n"
        original_message += f"💲 " + self.get_text('prezzo_originale') + ": " + original_price + "\n"
        original_message += f"💲 " + self.get_text('prezzo_scontato') + ": " + discounted_price
        
        # Migliora il messaggio con OpenAI
        improved_message = self.improve_message_with_openai(original_message)
        
        # Crea il notification_text ESATTAMENTE come nel canale database
        if improved_message != original_message:
            # OpenAI ha migliorato il messaggio, usalo così com'è (dovrebbe già essere in HTML)
            notification_text = improved_message
            logger.info("Test: using improved message with OpenAI with HTML formatting")
        else:
            # Usa il formato originale con escape HTML (stesso fallback del canale DB)
            escaped_title = self.escape_html(title or self.get_text('prodotto_amazon'))
            escaped_category = self.escape_html(category_name or self.get_text('senza_categoria'))
            escaped_original = self.escape_html(original_price)
            escaped_discounted = self.escape_html(discounted_price)
            
            notification_text = f"🔥 <b>" + self.get_text('nuovo_sconto_rilevato') + "</b> 🔥\n\n"
            notification_text += f"📦 <b>{escaped_title}</b>\n\n"
            notification_text += f"📂 " + self.get_text('categoria') + ": <b>{escaped_category}</b>\n"
            notification_text += f"💰 " + self.get_text('sconto') + ": <b>-{discount_percentage}%</b>\n"
            notification_text += f"💲 " + self.get_text('prezzo_originale') + ": <s>{escaped_original}</s>\n"
            notification_text += f"💲 " + self.get_text('prezzo_scontato') + ": <b>{escaped_discounted}</b>\n\n"
            notification_text += f"🔗 <a href='{amazon_url}'>{self.get_text('vai_al_prodotto')}</a>"
            logger.info("Test: using original message with HTML formatting")
        
        # Keyboard con opzioni (stesso formato del canale DB + pulsanti navigazione)
        keyboard = types.InlineKeyboardMarkup()
        
        # Aggiungi il pulsante con link di affiliazione (STESSO del canale DB)
        affiliate_url = self.add_affiliate_tag_to_url(amazon_url)
        purchase_text = self.get_purchase_button_text()
        affiliate_btn = types.InlineKeyboardButton(
            purchase_text, 
            url=affiliate_url
        )
        keyboard.add(affiliate_btn)
        
        # Pulsanti di navigazione del test (invece dei pulsanti di approvazione)
        modify_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_prompt'), callback_data="start_prompt_config")
        menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        
        keyboard.add(modify_btn, menu_btn)
        
        # Invia il messaggio ESATTAMENTE come nel canale database (con foto se disponibile)
        if image_url:
            try:
                # Usa send_photo come nel canale DB
                self.bot.send_photo(
                    call.message.chat.id,
                    image_url,
                    caption=notification_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                # Elimina il messaggio di caricamento
                try:
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                except:
                    pass
            except Exception as e:
                logger.error(f"Test: error sending photo: {e}, sending only text")
                # Fallback a solo testo, come nel canale DB
                try:
                    self.bot.edit_message_text(
                        notification_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                except Exception as e2:
                    self.bot.send_message(
                        call.message.chat.id,
                        notification_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
        else:
            # Nessuna immagine, usa send_message come nel canale DB
            try:
                self.bot.edit_message_text(
                    notification_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            except Exception as e:
                self.bot.send_message(
                    call.message.chat.id,
                    notification_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
        
        logger.info(f"Test prompt executed by user {call.from_user.id} for product {product_id}")

    def show_purchase_button_config_edit(self, call):
        """Mostra configurazione testo pulsante di acquisto (edit message)"""
        config = self.db.get_purchase_button_config()
        
        if config:
            button_text, is_active, created_by, created_at, updated_at = config
            
            config_text = f"🛒 <b>" + self.get_text('configurazione_pulsante_di_acquisto') + "</b>\n\n"
            if created_by:
                config_text += f"👤 " + self.get_text('configurato_da') + ": " + str(created_by) + "\n"
            if updated_at:
                config_text += f"🔄 " + self.get_text('aggiornato') + ": " + updated_at[:16] + "\n\n"
            else:
                config_text += f"\n"
            config_text += f"⬇️ " + self.get_text('testo_attuale_mostrato_nel_messaggio_sotto')
        else:
            config_text = f"🛒 <b>" + self.get_text('configurazione_pulsante_di_acquisto') + "</b>\n\n"
            config_text += f"⬇️ " + self.get_text('testo_attuale_mostrato_nel_messaggio_sotto')
            button_text = self.get_text('default_purchase_button')  # Default tradotto
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error modifying purchase button message: {e}")
        
        # Invia il testo attuale del pulsante in un messaggio separato
        if button_text:
            button_message = f"<code>{self.escape_html(button_text)}</code>"
            
            # Keyboard per il messaggio del testo pulsante
            keyboard_button = types.InlineKeyboardMarkup()
            modify_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_testo'), callback_data="start_purchase_button_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard_button.add(modify_btn)
            keyboard_button.add(menu_btn)
            
            # Invia il messaggio del testo pulsante separatamente
            try:
                self.bot.send_message(
                    call.message.chat.id,
                    button_message,
                    parse_mode='HTML',
                    reply_markup=keyboard_button
                )
            except Exception as e:
                logger.error(f"Error sending purchase button message: {e}")
        
        self.bot.answer_callback_query(call.id, "🛒 " + self.get_text('pulsante_di_acquisto'))
    
    def start_purchase_button_configuration(self, call):
        """Avvia il processo di configurazione del testo del pulsante di acquisto"""
        user_id = call.from_user.id
        self.user_states[user_id] = {'action': 'configuring_purchase_button'}
        
        config_text = f"✏️ <b>" + self.get_text('modifica_testo_pulsante_di_acquisto') + "</b>\n\n"
        config_text += f"📝 " + self.get_text('inserisci_il_nuovo_testo_per_il_pulsante_di_acquisto') + ":\n\n"
        config_text += f"💡 <i>" + self.get_text('esempi') + ":</i>\n"
        config_text += f"• 🛒 " + self.get_text('acquista_su_amazon') + "\n"
        config_text += f"• 🛍️ " + self.get_text('compra_ora') + "\n"
        config_text += f"• 💰 " + self.get_text('offerta_speciale') + "\n"
        config_text += f"• 🔥 " + self.get_text('approfitta_dell_offerta')
        
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annulla'), callback_data="cancel_purchase_button_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error starting purchase button configuration: {e}")
        
        self.bot.answer_callback_query(call.id, "✏️ " + self.get_text('modifica_testo'))
    
    def handle_purchase_button_configuration_input(self, message):
        """Gestisce l'input per la configurazione del testo del pulsante di acquisto"""
        user_id = message.from_user.id
        button_text = message.text.strip()
        
        if len(button_text) > 64:  # Limite Telegram per testo pulsante
            self.bot.send_message(
                message.chat.id,
                f"❌ <b>" + self.get_text('errore') + "</b>\n\n" +
                f"{self.get_text('il_testo_del_pulsante_è_troppo_lungo')}. " +
                f"{self.get_text('il_limite_massimo_è_di_64_caratteri')}.\n\n" +
                f"📝 " + self.get_text('inserisci_un_testo_più_breve') + ":",
                parse_mode='HTML'
            )
            return
        
        if not button_text:
            self.bot.send_message(
                message.chat.id,
                f"❌ <b>" + self.get_text('errore') + "</b>\n\n" +
                f"{self.get_text('il_testo_del_pulsante_non_può_essere_vuoto')}.\n\n" +
                f"📝 " + self.get_text('inserisci_il_testo_del_pulsante') + ":",
                parse_mode='HTML'
            )
            return
        
        try:
            # Salva la configurazione nel database
            self.db.update_purchase_button_config(button_text, user_id)
            
            # Rimuovi lo stato utente
            del self.user_states[user_id]
            
            success_text = f"✅ <b>" + self.get_text('testo_pulsante_aggiornato') + "</b>\n\n"
            success_text += f"🛒 " + self.get_text('nuovo_testo') + ": <code>" + self.escape_html(button_text) + "</code>\n\n"
            success_text += f"💡 " + self.get_text('il_nuovo_testo_verrà_utilizzato_in_tutti_i_messaggi_di_sconto') + "."
            
            keyboard = types.InlineKeyboardMarkup()
            config_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('configura_pulsante'), callback_data="show_purchase_button_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard.add(config_btn)
            keyboard.add(menu_btn)
            
            self.bot.send_message(
                message.chat.id,
                success_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
            logger.info(f"Purchase button text updated by user {user_id}: {button_text}")
            
        except Exception as e:
            logger.error(f"Error updating purchase button text: {e}")
            self.bot.send_message(
                message.chat.id,
                "❌ " + self.get_text('errore_durante_laggiornamento_del_testo_del_pulsante') + ". " + self.get_text('riprova') + ".",
                parse_mode='HTML'
            )
    
    def cancel_purchase_button_config(self, call):
        """Annulla la configurazione del pulsante e torna al messaggio del testo pulsante"""
        user_id = call.from_user.id
        
        # Rimuovi lo stato utente se esiste
        if user_id in self.user_states:
            del self.user_states[user_id]
        
        # Ottieni il testo del pulsante attuale
        config = self.db.get_purchase_button_config()
        if config:
            button_text = config[0]  # button_text
        else:
            button_text = self.get_text('default_purchase_button')  # Default tradotto
        
        # Modifica il messaggio corrente per mostrare il testo del pulsante
        button_message = f"<code>{self.escape_html(button_text)}</code>"
        
        # Keyboard per il messaggio del testo pulsante
        keyboard_button = types.InlineKeyboardMarkup()
        modify_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_testo'), callback_data="start_purchase_button_config")
        menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
        keyboard_button.add(modify_btn)
        keyboard_button.add(menu_btn)
        
        try:
            self.bot.edit_message_text(
                button_message,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard_button
            )
        except Exception as e:
            logger.error(f"Error modifying purchase button message: {e}")
        
        self.bot.answer_callback_query(call.id, "❌ " + self.get_text('annullo'))
    
    def cancel_prompt_config(self, call):
        """Annulla la configurazione del prompt e torna al messaggio del prompt"""
        user_id = call.from_user.id
        
        # Rimuovi lo stato utente se esiste
        if user_id in self.user_states:
            del self.user_states[user_id]
        
        # Ottieni il prompt attuale
        config = self.db.get_openai_prompt_config()
        if config and config[0]:  # Se c'è un prompt configurato
            prompt_text = config[0]
            
            # Modifica il messaggio corrente per mostrare il prompt
            prompt_message = f"📝 <b>" + self.get_text('prompt_ai_attuale') + ":</b>\n\n"
            prompt_message += f"<code>{self.escape_html(prompt_text)}</code>"
            
            # Keyboard per il messaggio del prompt (con tutti i pulsanti originali)
            keyboard_prompt = types.InlineKeyboardMarkup()
            test_btn = types.InlineKeyboardButton("🧪 " + self.get_text('testa_prompt'), callback_data="test_prompt")
            modify_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_prompt'), callback_data="start_prompt_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard_prompt.add(test_btn)
            keyboard_prompt.add(modify_btn)
            keyboard_prompt.add(menu_btn)
            
            try:
                self.bot.edit_message_text(
                    prompt_message,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard_prompt
                )
            except Exception as e:
                logger.error(f"Error modifying prompt message: {e}")
        else:
            # Se non c'è prompt configurato, mostra messaggio di default
            no_prompt_message = f"🤖 <b>" + self.get_text('nessun_prompt_configurato') + "</b>\n\n"
            no_prompt_message += f"📝 " + self.get_text('configura_un_prompt_personalizzato_per_migliorare_i_messaggi_di_sconto_con_openai') + "."
            
            keyboard_no_prompt = types.InlineKeyboardMarkup()
            config_btn = types.InlineKeyboardButton("➕ " + self.get_text('configura_prompt'), callback_data="start_prompt_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard_no_prompt.add(config_btn)
            keyboard_no_prompt.add(menu_btn)
            
            try:
                self.bot.edit_message_text(
                    no_prompt_message,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard_no_prompt
                )
            except Exception as e:
                logger.error(f"Error modifying no prompt message: {e}")
        
        self.bot.answer_callback_query(call.id, "❌ " + self.get_text('annullo'))
    
    def cancel_test_prompt(self, call):
        """Annulla il test prompt e torna al messaggio del prompt"""
        # Ottieni il prompt attuale
        config = self.db.get_openai_prompt_config()
        if config and config[0]:  # Se c'è un prompt configurato
            prompt_text = config[0]
            
            # Modifica il messaggio corrente per tornare al prompt
            prompt_message = f"📝 <b>" + self.get_text('prompt_ai_attuale') + ":</b>\n\n"
            prompt_message += f"<code>{self.escape_html(prompt_text)}</code>"
            
            # Keyboard per il messaggio del prompt (con tutti i pulsanti originali)
            keyboard_prompt = types.InlineKeyboardMarkup()
            test_btn = types.InlineKeyboardButton("🧪 " + self.get_text('testa_prompt'), callback_data="test_prompt")
            modify_btn = types.InlineKeyboardButton("⚙️ " + self.get_text('modifica_prompt'), callback_data="start_prompt_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard_prompt.add(test_btn)
            keyboard_prompt.add(modify_btn)
            keyboard_prompt.add(menu_btn)
            
            try:
                self.bot.edit_message_text(
                    prompt_message,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard_prompt
                )
            except Exception as e:
                logger.error(f"Error modifying prompt test message: {e}")
        else:
            # Se non c'è prompt configurato, mostra messaggio di default
            no_prompt_message = f"🤖 <b>" + self.get_text('nessun_prompt_configurato') + "</b>\n\n"
            no_prompt_message += f"📝 " + self.get_text('configura_un_prompt_personalizzato_per_migliorare_i_messaggi_di_sconto_con_openai') + "."
            
            keyboard_no_prompt = types.InlineKeyboardMarkup()
            config_btn = types.InlineKeyboardButton("➕ " + self.get_text('configura_prompt'), callback_data="start_prompt_config")
            menu_btn = types.InlineKeyboardButton("🏠 " + self.get_text('menu_principale'), callback_data="back_to_main_menu")
            keyboard_no_prompt.add(config_btn)
            keyboard_no_prompt.add(menu_btn)
            
            try:
                self.bot.edit_message_text(
                    no_prompt_message,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=keyboard_no_prompt
                )
            except Exception as e:
                logger.error(f"Error modifying no prompt test message: {e}")
        
        self.bot.answer_callback_query(call.id, "❌ " + self.get_text('test_annullato'))
    
    def start_prompt_configuration_edit(self, call):
        """Inizia il processo di configurazione prompt OpenAI (edit message)"""
        user_id = call.from_user.id
        config = self.db.get_openai_prompt_config()
        
        if config:
            prompt_text, is_active, created_by, created_at, updated_at = config
            status_text = "✅ " + self.get_text('attivo') if is_active else "❌ " + self.get_text('inattivo')
            
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_openai') + "</b>\n\n"
            config_text += f"📝 " + self.get_text('prompt_attuale') + ":\n<code>" + self.escape_html(prompt_text[:200]) + ("..." if len(prompt_text) > 200 else "") + "</code>\n\n"
            config_text += f"📊 " + self.get_text('stato') + ": " + status_text + "\n\n"
            config_text += f"💡 " + self.get_text('invia_il_nuovo_prompt_per_aggiornare_la_configurazione') + ":"
        else:
            config_text = f"🤖 <b>" + self.get_text('configurazione_prompt_openai') + "</b>\n\n"
            config_text += f"❌ " + self.get_text('nessun_prompt_configurato') + "\n\n" + "\n\n"
            config_text += f"📝 " + self.get_text('invia_il_prompt_personalizzato_che_openai_userà_per_migliorare_i_messaggi_degli_sconti') + ".\n\n"
            config_text += f"💡 " + self.get_text('esempio') + ": '" + self.get_text('esempio_prompt') + "'."
        
        self.user_states[user_id] = {
            'action': 'configuring_prompt',
            'chat_id': call.message.chat.id
        }
        
        # Keyboard con bottone annulla
        keyboard = types.InlineKeyboardMarkup()
        cancel_btn = types.InlineKeyboardButton("❌ " + self.get_text('annullo'), callback_data="cancel_prompt_config")
        keyboard.add(cancel_btn)
        
        try:
            self.bot.edit_message_text(
                config_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error modifying prompt configuration message: {e}")
    
    def initialize_default_configurations(self):
        """Inizializza le configurazioni di default nel database remoto se non sono impostate"""
        try:
            logger.info("🔧 Initializing default configurations...")
            
            # Ottieni la lingua corrente (ENV o config.json)
            current_language = self.translator.get_current_language()
            logger.info(f"📖 Current language for default: {current_language}")
            
            # Inizializza pulsante di acquisto se non esiste
            purchase_config = self.db.get_purchase_button_config()
            if not purchase_config:
                default_button_text = self.get_text('default_purchase_button')
                success = self.db.update_purchase_button_config(default_button_text, None)
                if success:
                    logger.info(f"✅ Purchase button initialized: '{default_button_text}'")
                else:
                    logger.warning("⚠️ Error initializing purchase button")
            else:
                logger.info("ℹ️ Purchase button already configured")
            
            # Inizializza prompt AI se non esiste
            prompt_config = self.db.get_openai_prompt_config()
            if not prompt_config:
                default_prompt = self.get_text('default_ai_prompt')
                success = self.db.update_openai_prompt_config(default_prompt, None)
                if success:
                    logger.info(f"✅ Prompt AI initialized: '{default_prompt[:50]}...'")
                else:
                    logger.warning("⚠️ Error initializing prompt AI")
            else:
                logger.info("ℹ️ Prompt AI already configured")
            
            # Inizializza configurazione cronjob se non esiste
            cronjob_config = self.db.get_cronjob_config()
            if not cronjob_config:
                # Valori di default: 60 min intervallo, 2 min delay, disabilitato
                default_check_interval = 60
                default_product_delay = 2
                default_is_active = False
                success = self.db.update_cronjob_config(
                    default_check_interval, 
                    default_product_delay, 
                    default_is_active, 
                    None
                )
                if success:
                    logger.info(f"✅ Cronjob initialized: interval {default_check_interval}min, delay {default_product_delay}min, active: {default_is_active}")
                else:
                    logger.warning("⚠️ Error initializing cronjob")
            else:
                logger.info("ℹ️ Cronjob already configured")
            
            logger.info("🎯 Initializing configurations completed")
            
        except Exception as e:
            logger.error(f"❌ Error during initialization configurations: {e}")
    
    def get_purchase_button_text(self):
        """Ottiene il testo attuale del pulsante di acquisto dalla configurazione"""
        config = self.db.get_purchase_button_config()
        if config:
            return config[0]  # button_text
        return self.get_text('default_purchase_button')  # Default tradotto

    def show_language_settings(self, call):
        """Mostra il menu delle impostazioni lingua"""
        try:
            current_lang = self.translator.get_current_language()
            available_langs = self.translator.get_available_languages()
            
            if not available_langs:
                self.bot.edit_message_text(
                    self.get_text('no_languages_available'),
                    call.message.chat.id,
                    call.message.message_id
                )
                return
            
            # Crea il messaggio con lingua corrente
            message_text = f"{self.get_text('current_language', language=current_lang)}\n\n{self.get_text('select_language')}"
            
            # Crea keyboard con le lingue disponibili
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            
            for lang in available_langs:
                display_name = self.translator.get_language_display_name(lang)
                current_indicator = " ✅" if lang == current_lang else ""
                button_text = f"{display_name}{current_indicator}"
                callback_data = f"set_language_{lang}"
                keyboard.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))
            
            # Aggiungi pulsante indietro
            keyboard.add(types.InlineKeyboardButton(
                self.get_text('back'), 
                callback_data="back_to_main_menu"
            ))
            
            self.bot.edit_message_text(
                message_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error in show_language_settings: {e}")
    
    def set_language(self, call, language: str):
        """Imposta una nuova lingua"""
        try:
            if self.translator.set_language(language):
                # Lingua cambiata con successo
                success_message = self.get_text('language_changed')
                
                # Mostra messaggio di conferma
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton(
                    self.get_text('main_menu'), 
                    callback_data="back_to_main_menu"
                ))
                
                self.bot.edit_message_text(
                    success_message,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=keyboard
                )
                
                logger.info(f"Language changed in {language} by user {call.from_user.id}")
            else:
                # Errore nel cambio lingua
                self.bot.answer_callback_query(
                    call.id, 
                    f"❌ " + self.get_text('errore_nel_cambio_lingua') + ": " + language
                )
                
        except Exception as e:
            logger.error(f"Error in set_language: {e}")
            self.bot.answer_callback_query(call.id, "❌ " + self.get_text('errore_interno'))

    def run(self):
        """Avvia il bot"""
        logger.info("Starting bot...")
        try:
            logger.info("📡 Starting Telegram polling...")
            self.bot.infinity_polling()
        except Exception as e:
            logger.error(f"Error during bot execution: {e}")
            raise

if __name__ == "__main__":
    try:
        bot = AmazonBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
