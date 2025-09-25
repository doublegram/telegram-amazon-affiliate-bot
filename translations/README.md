# 🌐 Sistema di Traduzioni

## 📋 Panoramica

Il sistema di traduzioni permette di supportare più lingue nel bot Telegram. Le traduzioni sono gestite tramite file JSON e la configurazione viene salvata localmente.

## 📁 Struttura File

```
translations/
├── config.json          # Configurazione lingua corrente (NON tradurre)
├── Italian.json         # Traduzioni italiane (default)
├── English.json         # Traduzioni inglesi
├── Spanish.json         # Traduzioni spagnole
├── French.json          # Traduzioni francesi
└── [NomeLingua].json    # Altri file lingue
```

## ⚙️ Come Funziona

### 1. **File di Configurazione** (`config.json`)
```json
{
  "current_language": "Italian",
  "last_updated": "2025-09-24T13:00:00Z"
}
```

### 2. **File di Traduzione** (`[Lingua].json`)
```json
{
  "welcome_message": "Benvenuto! 👋",
  "main_menu": "🏠 Menu Principale",
  "language_changed": "✅ Lingua cambiata con successo!",
  "current_language": "Lingua attuale: {language}"
}
```

## 🛠️ Aggiungere Nuove Lingue

1. **Crea un nuovo file JSON** nella cartella `translations/`
   - Nome file: `[NomeLingua].json` (es. `German.json`)
   
2. **Copia la struttura** da un file esistente (es. `Italian.json`)

3. **Traduci tutti i testi** mantenendo:
   - Le **chiavi** identiche (es. `"welcome_message"`)
   - I **placeholder** intatti (es. `{language}`)
   - Le **emoji** se desiderate

4. **Il file apparirà automaticamente** nel menu "🌐 Impostazioni Lingua"

## 🎨 Nomi di Visualizzazione

I nomi delle lingue nel menu sono personalizzabili in `translation_manager.py`:

```python
display_names = {
    'Italian': '🇮🇹 Italiano',
    'English': '🇺🇸 English', 
    'Spanish': '🇪🇸 Español',
    'French': '🇫🇷 Français'
}
```

## 🔧 Utilizzo nel Codice

```python
# Ottenere testo tradotto
text = self.get_text('welcome_message')

# Con parametri
text = self.get_text('current_language', language="Italian")

# Controllo esistenza traduzione
if self.translator.has_translation("my_key"):
    # ...
```

## 📝 Chiavi Traduzione Disponibili

### Menu e Navigazione
- `welcome_message` - Messaggio di benvenuto
- `main_menu` - Menu Principale
- `back` - Indietro
- `cancel` - Annulla
- `save` - Salva
- `delete` - Elimina
- `edit` - Modifica
- `add` - Aggiungi
- `settings` - Impostazioni

### Funzionalità Bot
- `categories` - Gestione Categorie
- `products` - Gestione Prodotti
- `cronjob` - Configurazione Cronjob
- `channel_db` - Canale Database
- `admin_management` - Gestione Admin
- `prompt_ai` - Prompt AI
- `purchase_button` - Pulsante di Acquisto
- `slug_amazon` - Slug Amazon

### Sistema Lingua
- `language_settings` - Impostazioni Lingua
- `language_changed` - Conferma cambio lingua
- `current_language` - Lingua corrente: {language}
- `select_language` - Seleziona una lingua
- `no_languages_available` - Nessuna lingua disponibile

## 🚨 Note Importanti

1. **NON modificare** `config.json` manualmente
2. **NON eliminare** chiavi esistenti dai file di traduzione
3. **Mantenere** i placeholder `{parametro}` nei testi
4. **Testare** sempre le traduzioni prima del deployment
5. Il file `config.json` è **escluso** automaticamente dalla lista lingue

## 🔄 Ricaricamento

Le traduzioni vengono ricaricate automaticamente quando:
- Si cambia lingua dal menu
- Si riavvia il bot
- Si chiama `translator.reload_translations()`
