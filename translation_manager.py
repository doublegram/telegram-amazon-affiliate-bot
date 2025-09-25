import json
import os
from typing import Dict, List, Optional
import logging

class TranslationManager:
    """Gestisce il sistema di traduzioni del bot"""
    
    def __init__(self, translations_dir: str = "translations"):
        self.translations_dir = translations_dir
        self.config_file = os.path.join(translations_dir, "config.json")
        self.current_language = "Italian"  # Default
        self.translations = {}
        self.available_languages = []
        
        # Inizializza il sistema
        self._load_config()
        self._load_available_languages()
        self._load_current_translations()
    
    def _load_config(self):
        """Carica la configurazione lingua dal file config.json"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.current_language = config.get('current_language', 'Italian')
                    logging.info(f"📖 Configurazione lingua caricata: {self.current_language}")
            else:
                logging.warning(f"⚠️ File config non trovato, usando default: {self.current_language}")
        except Exception as e:
            logging.error(f"❌ Errore caricamento config lingua: {e}")
    
    def _save_config(self):
        """Salva la configurazione lingua nel file config.json"""
        try:
            os.makedirs(self.translations_dir, exist_ok=True)
            config = {
                "current_language": self.current_language,
                "last_updated": self._get_current_timestamp()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logging.info(f"💾 Configurazione lingua salvata: {self.current_language}")
        except Exception as e:
            logging.error(f"❌ Errore salvataggio config lingua: {e}")
    
    def _load_available_languages(self):
        """Carica l'elenco delle lingue disponibili dai file JSON"""
        try:
            if not os.path.exists(self.translations_dir):
                os.makedirs(self.translations_dir, exist_ok=True)
                logging.warning(f"📁 Cartella traduzioni creata: {self.translations_dir}")
            
            self.available_languages = []
            for filename in os.listdir(self.translations_dir):
                if filename.endswith('.json') and filename != 'config.json':
                    language_name = filename[:-5]  # Rimuove .json
                    self.available_languages.append(language_name)
            
            self.available_languages.sort()
            logging.info(f"🌐 Lingue disponibili: {self.available_languages}")
            
        except Exception as e:
            logging.error(f"❌ Errore caricamento lingue disponibili: {e}")
    
    def _load_current_translations(self):
        """Carica le traduzioni per la lingua corrente"""
        try:
            language_file = os.path.join(self.translations_dir, f"{self.current_language}.json")
            
            if os.path.exists(language_file):
                with open(language_file, 'r', encoding='utf-8') as f:
                    self.translations = json.load(f)
                logging.info(f"📚 Traduzioni caricate per: {self.current_language}")
            else:
                logging.error(f"❌ File traduzioni non trovato: {language_file}")
                self.translations = {}
                
        except Exception as e:
            logging.error(f"❌ Errore caricamento traduzioni: {e}")
            self.translations = {}
    
    def get_available_languages(self) -> List[str]:
        """Restituisce l'elenco delle lingue disponibili"""
        return self.available_languages.copy()
    
    def get_current_language(self) -> str:
        """Restituisce la lingua corrente"""
        return self.current_language
    
    def set_language(self, language: str) -> bool:
        """Imposta la lingua corrente e ricarica le traduzioni"""
        if language not in self.available_languages:
            logging.error(f"❌ Lingua non disponibile: {language}")
            return False
        
        self.current_language = language
        self._save_config()
        self._load_current_translations()
        logging.info(f"✅ Lingua cambiata in: {language}")
        return True
    
    def get_text(self, key: str, **kwargs) -> str:
        """
        Ottiene il testo tradotto per la chiave specificata
        
        Args:
            key: Chiave della traduzione
            **kwargs: Parametri per il formatting del testo (es. {language})
        
        Returns:
            Testo tradotto o la chiave se non trovata
        """
        try:
            text = self.translations.get(key, key)
            
            # Applica il formatting se ci sono parametri
            if kwargs:
                text = text.format(**kwargs)
            
            return text
            
        except Exception as e:
            logging.error(f"❌ Errore get_text per chiave '{key}': {e}")
            return key
    
    def reload_translations(self):
        """Ricarica le traduzioni (utile se i file vengono modificati)"""
        self._load_available_languages()
        self._load_current_translations()
        logging.info("🔄 Traduzioni ricaricate")
    
    def _get_current_timestamp(self) -> str:
        """Restituisce il timestamp corrente in formato ISO"""
        from datetime import datetime
        return datetime.now().isoformat() + 'Z'
    
    def get_language_display_name(self, language: str) -> str:
        """Restituisce il nome di visualizzazione per una lingua"""
        # Mappa per nomi di visualizzazione personalizzati
        display_names = {
            'Italian': '🇮🇹 Italiano',
            'English': '🇺🇸 English',
            'Spanish': '🇪🇸 Español',
            'French': '🇫🇷 Français',
            'German': '🇩🇪 Deutsch',
            'Portuguese': '🇵🇹 Português',
            'Russian': '🇷🇺 Русский',
            'Chinese': '🇨🇳 中文',
            'Japanese': '🇯🇵 日本語',
            'Korean': '🇰🇷 한국어'
        }
        
        return display_names.get(language, f"🌐 {language}")
    
    def has_translation(self, key: str) -> bool:
        """Controlla se esiste una traduzione per la chiave specificata"""
        return key in self.translations
    
    def get_translation_keys(self) -> List[str]:
        """Restituisce tutte le chiavi di traduzione disponibili"""
        return list(self.translations.keys())
