# Usa Python 3.11 slim come base
FROM python:3.11-slim

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file dei requirements
COPY requirements.txt .

# Installa le dipendenze
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice dell'applicazione
COPY . .

# Espone la porta (opzionale, per future estensioni)
EXPOSE 8000

# Comando per avviare il bot
CMD ["python", "bot.py"]


