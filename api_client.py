import os
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AffiliateAPIClient:
    """
    Wrapper client per le chiamate alle API di affiliate.doublegram.com
    Gestisce SOLO autenticazione e chiamate HTTP base
    """
    
    def __init__(self, api_url: str = None, license_key: str = None, email: str = None):
        """
        Inizializza il client API
        
        Args:
            api_url: URL base dell'API (default da env)
            license_key: Chiave licenza (default da env)
            email: Email registrata (default da env)
        """
        self.api_url = api_url or os.getenv('AFFILIATE_API_URL', 'https://affiliate.doublegram.com')
        self.license_key = license_key or os.getenv('LICENSE_CODE')
        self.email = email or os.getenv('DOUBLEGRAM_EMAIL')
        
        # Headers standard per tutte le richieste
        self.headers = {
            'license-key': self.license_key,
            'email': self.email,
            'product-code': 'DGAFF',
            'Content-Type': 'application/json'
        }
        
        # Timeout per le richieste
        self.timeout = 30
        
        logger.info(f"🔧 AffiliateAPIClient inizializzato - URL: {self.api_url}")
    
    def make_request(self, method: str, endpoint: str, data: dict = None, params: dict = None) -> dict:
        """
        Effettua una richiesta HTTP all'API
        
        Args:
            method: Metodo HTTP (GET, POST, PUT, DELETE)
            endpoint: Endpoint dell'API (es: /api/bot/users)
            data: Dati da inviare nel body (per POST/PUT)
            params: Parametri query string (per GET)
            
        Returns:
            dict: Risposta JSON dell'API
            
        Raises:
            Exception: In caso di errore nella richiesta
        """
        url = f"{self.api_url}{endpoint}"
        
        try:
            logger.debug(f"🌐 {method} {endpoint}")
            
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data if data else None,
                params=params if params else None,
                timeout=self.timeout
            )
            
            # Log della risposta
            logger.debug(f"📡 Response: {response.status_code} - {response.text[:200]}...")
            
            # Gestione errori HTTP
            if response.status_code == 401:
                logger.error("❌ Licenza non valida o scaduta")
                raise Exception("Licenza non valida o scaduta")
            elif response.status_code == 403:
                logger.error("❌ Accesso negato")
                raise Exception("Accesso negato")
            elif response.status_code == 404:
                logger.warning("⚠️ Risorsa non trovata")
                return {"success": False, "error": "Risorsa non trovata"}
            elif response.status_code >= 400:
                logger.error(f"❌ Errore HTTP {response.status_code}: {response.text}")
                raise Exception(f"Errore API: {response.status_code} - {response.text}")
            
            # Parse JSON response
            try:
                result = response.json()
                return result
            except ValueError as e:
                logger.error(f"❌ Errore parsing JSON: {e}")
                raise Exception(f"Risposta API non valida: {response.text}")
                
        except requests.exceptions.Timeout:
            logger.error(f"⏰ Timeout richiesta {method} {endpoint}")
            raise Exception(f"Timeout richiesta API: {endpoint}")
        except requests.exceptions.ConnectionError:
            logger.error(f"🔌 Errore connessione {method} {endpoint}")
            raise Exception(f"Errore connessione API: {endpoint}")
        except requests.exceptions.RequestException as e:
            logger.error(f"🌐 Errore richiesta {method} {endpoint}: {e}")
            raise Exception(f"Errore richiesta API: {e}")