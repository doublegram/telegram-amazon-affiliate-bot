import os
from typing import Optional, List
from api_client import AffiliateAPIClient

class DatabaseManager:
    def __init__(self, db_path: str):
        self.api_client = AffiliateAPIClient()
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Aggiunge un nuovo utente al database tramite API"""
        data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name
        }
        
        result = self.api_client.make_request('POST', '/api/bot/users', data)
        
        if not result.get('success', False):
            raise Exception(f"Errore aggiunta utente: {result.get('error', 'Unknown error')}")
    
    def log_interaction(self, user_id: int, command: str, message: str = None):
        """Registra un'interazione dell'utente tramite API"""
        data = {
            'command': command,
            'message': message
        }
        
        result = self.api_client.make_request('POST', f'/api/bot/users/{user_id}/interactions', data)
        
        if not result.get('success', False):
            raise Exception(f"Errore log interaction: {result.get('error', 'Unknown error')}")
    
    def get_user_interactions(self, user_id: int, limit: int = 10) -> List[tuple]:
        """Ottiene le ultime interazioni di un utente tramite API"""
        params = {'limit': limit}
        
        result = self.api_client.make_request('GET', f'/api/bot/users/{user_id}/interactions', params=params)
        
        if not result.get('success', False):
            raise Exception(f"Errore get user interactions: {result.get('error', 'Unknown error')}")
        
        # Converte il formato API in tupla come SQLite
        interactions = []
        for item in result.get('data', []):
            interactions.append((
                item.get('command'),
                item.get('message'), 
                item.get('timestamp')
            ))
        return interactions
    
    def update_user_activity(self, user_id: int):
        """Aggiorna l'ultima attività dell'utente tramite API"""
        result = self.api_client.make_request('PUT', f'/api/bot/users/{user_id}/activity')
        
        if not result.get('success', False):
            raise Exception(f"Errore update user activity: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire le categorie
    def add_category(self, name: str, description: str, created_by: int) -> bool:
        """Aggiunge una nuova categoria al database tramite API"""
        data = {
            'name': name,
            'description': description,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('POST', '/api/bot/categories', data)
        
        if result.get('success'):
            return True
        elif 'already exists' in result.get('error', '').lower():
            return False  # Categoria già esistente
        else:
            raise Exception(f"Errore add category: {result.get('error', 'Unknown error')}")
    
    def get_all_categories(self) -> List[tuple]:
        """Ottiene tutte le categorie tramite API"""
        result = self.api_client.make_request('GET', '/api/bot/categories')
        
        if not result.get('success', False):
            raise Exception(f"Errore get all categories: {result.get('error', 'Unknown error')}")
        
        # Converte il formato API in tupla come SQLite
        categories = []
        for item in result.get('data', []):
            categories.append((
                item.get('id'),
                item.get('name'),
                item.get('description'),
                item.get('telegram_group_link'),
                item.get('created_by'),
                item.get('created_at')
            ))
        return categories
    
    def delete_category(self, category_id: int) -> bool:
        """Elimina una categoria dal database tramite API"""
        result = self.api_client.make_request('DELETE', f'/api/bot/categories/{category_id}')
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Categoria non trovata
        else:
            raise Exception(f"Errore delete category: {result.get('error', 'Unknown error')}")
    
    def get_category_by_id(self, category_id: int) -> Optional[tuple]:
        """Ottiene una categoria specifica per ID tramite API"""
        result = self.api_client.make_request('GET', f'/api/bot/categories/{category_id}')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('id'),
                item.get('name'),
                item.get('description'),
                item.get('telegram_group_link'),
                item.get('created_by'),
                item.get('created_at')
            )
        elif 'not found' in result.get('error', '').lower():
            return None  # Categoria non trovata
        else:
            raise Exception(f"Errore get category by id: {result.get('error', 'Unknown error')}")
    
    def update_category_telegram_link(self, category_id: int, telegram_link: str) -> bool:
        """Aggiorna il link del gruppo Telegram per una categoria tramite API"""
        data = {'telegram_link': telegram_link}
        
        result = self.api_client.make_request('PUT', f'/api/bot/categories/{category_id}/telegram-link', data)
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Categoria non trovata
        else:
            raise Exception(f"Errore update category telegram link: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire i prodotti
    def add_product(self, amazon_url: str, title: str = None, image_url: str = None, category_id: int = None, added_by: int = None) -> int:
        """Aggiunge un nuovo prodotto al database tramite API e restituisce l'ID"""
        data = {
            'amazon_url': amazon_url,
            'title': title,
            'image_url': image_url,
            'category_id': category_id,
            'added_by': added_by
        }
        
        result = self.api_client.make_request('POST', '/api/bot/products', data)
        
        if result.get('success'):
            return result.get('product_id', 0)
        else:
            raise Exception(f"Errore add product: {result.get('error', 'Unknown error')}")
    
    def update_product_details(self, product_id: int, title: str = None, image_url: str = None) -> bool:
        """Aggiorna titolo e immagine di un prodotto tramite API"""
        data = {}
        if title is not None:
            data['title'] = title
        if image_url is not None:
            data['image_url'] = image_url
        
        if not data:
            return False  # Nessun dato da aggiornare
        
        result = self.api_client.make_request('PUT', f'/api/bot/products/{product_id}/details', data)
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Prodotto non trovato
        else:
            raise Exception(f"Errore update product details: {result.get('error', 'Unknown error')}")
    
    def update_product_category(self, product_id: int, category_id: int) -> bool:
        """Aggiorna la categoria di un prodotto tramite API"""
        data = {'category_id': category_id}
        
        result = self.api_client.make_request('PUT', f'/api/bot/products/{product_id}/category', data)
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Prodotto non trovato
        else:
            raise Exception(f"Errore update product category: {result.get('error', 'Unknown error')}")
    
    def get_product_by_id(self, product_id: int) -> Optional[tuple]:
        """Ottiene un prodotto specifico per ID tramite API"""
        result = self.api_client.make_request('GET', f'/api/bot/products/{product_id}')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('id'),
                item.get('amazon_url'),
                item.get('title'),
                item.get('image_url'),
                item.get('category_id'),
                item.get('added_by'),
                item.get('created_at'),
                item.get('category_name')
            )
        elif 'not found' in result.get('error', '').lower():
            return None  # Prodotto non trovato
        else:
            raise Exception(f"Errore get product by id: {result.get('error', 'Unknown error')}")
    
    def get_products_by_category(self, category_id: int) -> List[tuple]:
        """Ottiene tutti i prodotti di una categoria tramite API"""
        params = {'category_id': category_id}
        
        result = self.api_client.make_request('GET', '/api/bot/products', params=params)
        
        if not result.get('success', False):
            raise Exception(f"Errore get products by category: {result.get('error', 'Unknown error')}")
        
        # Converte il formato API in tupla come SQLite
        products = []
        for item in result.get('data', []):
            products.append((
                item.get('id'),
                item.get('amazon_url'),
                item.get('title'),
                item.get('added_by'),
                item.get('created_at')
            ))
        return products
    
    def get_all_products(self) -> List[tuple]:
        """Ottiene tutti i prodotti con informazioni categoria tramite API"""
        result = self.api_client.make_request('GET', '/api/bot/products')
        
        if not result.get('success', False):
            raise Exception(f"Errore get all products: {result.get('error', 'Unknown error')}")
        
        # Converte il formato API in tupla come SQLite
        products = []
        for item in result.get('data', []):
            products.append((
                item.get('id'),
                item.get('amazon_url'),
                item.get('title'),
                item.get('image_url'),
                item.get('category_id'),
                item.get('added_by'),
                item.get('created_at'),
                item.get('category_name')
            ))
        return products
    
    def delete_product(self, product_id: int) -> bool:
        """Elimina un prodotto e tutti i suoi sconti associati tramite API"""
        result = self.api_client.make_request('DELETE', f'/api/bot/products/{product_id}')
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Prodotto non trovato
        else:
            raise Exception(f"Errore delete product: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire gli sconti
    def add_product_discount(self, product_id: int, discount_percentage: int, original_price: str, 
                           discounted_price: str, currency: str = '€') -> int:
        """Aggiunge un nuovo sconto rilevato per un prodotto tramite API"""
        data = {
            'discount_percentage': discount_percentage,
            'original_price': original_price,
            'discounted_price': discounted_price,
            'currency': currency
        }
        
        result = self.api_client.make_request('POST', f'/api/bot/products/{product_id}/discounts', data)
        
        if result.get('success'):
            return result.get('discount_id', 0)
        else:
            raise Exception(f"Errore add product discount: {result.get('error', 'Unknown error')}")
    
    def get_latest_discount_for_product(self, product_id: int) -> Optional[tuple]:
        """Ottiene l'ultimo sconto rilevato per un prodotto tramite API"""
        result = self.api_client.make_request('GET', f'/api/bot/products/{product_id}/discounts/latest')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('discount_percentage'),
                item.get('original_price'),
                item.get('discounted_price'),
                item.get('currency'),
                item.get('detected_at')
            )
        else:
            return None  # Nessuno sconto trovato
    
    def discount_data_changed(self, product_id: int, discount_percentage: int, 
                            original_price: str, discounted_price: str) -> bool:
        """Controlla se i dati dello sconto sono cambiati rispetto all'ultima rilevazione tramite API"""
        data = {
            'discount_percentage': discount_percentage,
            'original_price': original_price,
            'discounted_price': discounted_price
        }
        
        result = self.api_client.make_request('POST', f'/api/bot/products/{product_id}/discounts/check-changed', data)
        
        if result.get('success'):
            return result.get('data_changed', True)  # Default True se non specificato
        else:
            raise Exception(f"Errore discount data changed: {result.get('error', 'Unknown error')}")
    
    # Metodi per la configurazione cronjob
    def get_cronjob_config(self) -> Optional[tuple]:
        """Ottiene la configurazione del cronjob tramite API"""
        result = self.api_client.make_request('GET', '/api/config/cronjob')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('check_interval_minutes'),
                item.get('product_delay_minutes'),
                item.get('is_active'),
                item.get('last_run'),
                item.get('created_by')
            )
        else:
            return None  # Nessuna configurazione trovata
    
    def update_cronjob_config(self, check_interval: int, product_delay: int, 
                            is_active: bool, created_by: int) -> bool:
        """Aggiorna o crea la configurazione del cronjob tramite API"""
        data = {
            'check_interval_minutes': check_interval,
            'product_delay_minutes': product_delay,
            'is_active': is_active,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('PUT', '/api/config/cronjob', data)
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update cronjob config: {result.get('error', 'Unknown error')}")
    
    def update_cronjob_last_run(self) -> bool:
        """Aggiorna il timestamp dell'ultima esecuzione del cronjob tramite API"""
        result = self.api_client.make_request('PUT', '/api/config/cronjob/last-run')
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update cronjob last run: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire il canale di approvazione
    def get_channel_config(self) -> Optional[tuple]:
        """Ottiene la configurazione del canale di approvazione tramite API"""
        result = self.api_client.make_request('GET', '/api/config/channel')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('channel_link'),
                item.get('channel_id'),
                item.get('is_active'),
                item.get('created_by')
            )
        else:
            return None  # Nessuna configurazione trovata
    
    def update_channel_config(self, channel_link: str, channel_id: str = None, 
                            is_active: bool = True, created_by: int = None) -> bool:
        """Aggiorna o crea la configurazione del canale tramite API"""
        data = {
            'channel_link': channel_link,
            'channel_id': channel_id,
            'is_active': is_active,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('PUT', '/api/config/channel', data)
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update channel config: {result.get('error', 'Unknown error')}")
    
    def add_approval_message(self, product_id: int, discount_id: int, 
                           channel_message_id: int, improved_message: str = None) -> int:
        """Aggiunge un messaggio di approvazione tramite API"""
        data = {
            'product_id': product_id,
            'discount_id': discount_id,
            'channel_message_id': channel_message_id,
            'improved_message': improved_message
        }
        
        result = self.api_client.make_request('POST', '/api/config/approval-messages', data)
        
        if result.get('success'):
            return result.get('approval_id', 0)
        else:
            raise Exception(f"Errore add approval message: {result.get('error', 'Unknown error')}")
    
    def approve_message(self, approval_id: int, approved_by: int) -> bool:
        """Approva un messaggio tramite API"""
        data = {'approved_by': approved_by}
        
        result = self.api_client.make_request('PUT', f'/api/config/approval-messages/{approval_id}/approve', data)
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Messaggio non trovato
        else:
            raise Exception(f"Errore approve message: {result.get('error', 'Unknown error')}")
    
    def get_approval_by_message_id(self, channel_message_id: int) -> Optional[tuple]:
        """Ottiene un messaggio di approvazione per message_id tramite API"""
        result = self.api_client.make_request('GET', f'/api/config/approval-messages/by-channel/{channel_message_id}')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('id'),
                item.get('product_id'),
                item.get('discount_id'),
                item.get('is_approved'),
                item.get('improved_message')
            )
        else:
            return None  # Messaggio non trovato
    
    # Metodi per gestire il prompt personalizzato OpenAI
    def get_openai_prompt_config(self):
        """Ottiene la configurazione del prompt OpenAI tramite API"""
        result = self.api_client.make_request('GET', '/api/config/openai-prompt')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('prompt_text'),
                item.get('is_active'),
                item.get('created_by'),
                item.get('created_at'),
                item.get('updated_at')
            )
        else:
            return None  # Nessuna configurazione trovata
    
    def update_openai_prompt_config(self, prompt_text: str, created_by: int):
        """Aggiorna o crea la configurazione del prompt OpenAI tramite API"""
        data = {
            'prompt_text': prompt_text,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('PUT', '/api/config/openai-prompt', data)
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update openai prompt config: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire lo slug Amazon affiliazione
    def get_amazon_affiliate_config(self):
        """Ottiene la configurazione dello slug Amazon tramite API"""
        result = self.api_client.make_request('GET', '/api/config/amazon-affiliate')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('affiliate_tag'),
                item.get('is_active'),
                item.get('created_by'),
                item.get('created_at'),
                item.get('updated_at')
            )
        else:
            return None  # Nessuna configurazione trovata
    
    def update_amazon_affiliate_config(self, affiliate_tag: str, created_by: int):
        """Aggiorna o crea la configurazione dello slug Amazon tramite API"""
        data = {
            'affiliate_tag': affiliate_tag,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('PUT', '/api/config/amazon-affiliate', data)
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update amazon affiliate config: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire gli admin aggiuntivi
    def add_admin_user(self, user_id: int, username: str = None, first_name: str = None, 
                       last_name: str = None, added_by: int = None) -> bool:
        """Aggiunge un nuovo admin al database tramite API"""
        data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'added_by': added_by
        }
        
        result = self.api_client.make_request('POST', '/api/bot/admin-users', data)
        
        if result.get('success'):
            return True
        elif 'already exists' in result.get('error', '').lower():
            return False  # L'utente è già admin
        else:
            raise Exception(f"Errore add admin user: {result.get('error', 'Unknown error')}")
    
    def remove_admin_user(self, user_id: int) -> bool:
        """Rimuove un admin dal database tramite API"""
        result = self.api_client.make_request('DELETE', f'/api/bot/admin-users/{user_id}')
        
        if result.get('success'):
            return True
        elif 'not found' in result.get('error', '').lower():
            return False  # Admin non trovato
        else:
            raise Exception(f"Errore remove admin user: {result.get('error', 'Unknown error')}")
    
    def get_all_admin_users(self) -> list:
        """Ottiene tutti gli admin aggiuntivi tramite API"""
        result = self.api_client.make_request('GET', '/api/bot/admin-users')
        
        if not result.get('success', False):
            raise Exception(f"Errore get all admin users: {result.get('error', 'Unknown error')}")
        
        admin_users = []
        for item in result.get('data', []):
            admin_users.append((
                item.get('user_id'),
                item.get('username'),
                item.get('first_name'),
                item.get('last_name'),
                item.get('is_active'),
                item.get('added_by'),
                item.get('created_at')
            ))
        return admin_users
    
    def is_admin_user(self, user_id: int) -> bool:
        """Controlla se un utente è admin aggiuntivo tramite API"""
        result = self.api_client.make_request('GET', f'/api/bot/admin-users/{user_id}/check')
        
        if result.get('success'):
            return result.get('is_admin', False)
        else:
            raise Exception(f"Errore is admin user: {result.get('error', 'Unknown error')}")
    
    def get_admin_user_info(self, user_id: int) -> tuple:
        """Ottiene informazioni su un admin specifico tramite API"""
        result = self.api_client.make_request('GET', f'/api/bot/admin-users/{user_id}')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('user_id'),
                item.get('username'),
                item.get('first_name'),
                item.get('last_name'),
                item.get('is_active'),
                item.get('added_by'),
                item.get('created_at')
            )
        elif 'not found' in result.get('error', '').lower():
            return None  # Admin non trovato
        else:
            raise Exception(f"Errore get admin user info: {result.get('error', 'Unknown error')}")
    
    # Metodi per gestire l'approvazione automatica
    def get_auto_approval_config(self):
        """Ottiene la configurazione dell'approvazione automatica tramite API"""
        result = self.api_client.make_request('GET', '/api/config/auto-approval')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('is_enabled'),
                item.get('created_by'),
                item.get('created_at'),
                item.get('updated_at')
            )
        else:
            return None  # Nessuna configurazione trovata
    
    def update_auto_approval_config(self, is_enabled: bool, created_by: int):
        """Aggiorna o crea la configurazione dell'approvazione automatica tramite API"""
        data = {
            'is_enabled': is_enabled,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('PUT', '/api/config/auto-approval', data)
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update auto approval config: {result.get('error', 'Unknown error')}")
    
    def get_purchase_button_config(self):
        """Ottiene la configurazione del testo del pulsante di acquisto tramite API"""
        result = self.api_client.make_request('GET', '/api/config/purchase-button')
        
        if result.get('success') and result.get('data'):
            item = result['data']
            return (
                item.get('button_text'),
                item.get('is_active'),
                item.get('created_by'),
                item.get('created_at'),
                item.get('updated_at')
            )
        else:
            return None  # Nessuna configurazione trovata
    
    def update_purchase_button_config(self, button_text: str, created_by: int):
        """Aggiorna o crea la configurazione del testo del pulsante di acquisto tramite API"""
        data = {
            'button_text': button_text,
            'created_by': created_by
        }
        
        result = self.api_client.make_request('PUT', '/api/config/purchase-button', data)
        
        if result.get('success'):
            return True
        else:
            raise Exception(f"Errore update purchase button config: {result.get('error', 'Unknown error')}")
