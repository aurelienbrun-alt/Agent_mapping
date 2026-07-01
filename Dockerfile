FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs output reports docs/cache

EXPOSE 8080

CMD ["python", "-m", "webapp.main"]
