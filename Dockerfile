FROM python:3.10-slim
ARG BUILD_NUMBER=dev
ENV BUILD_NUMBER=$BUILD_NUMBER
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
RUN mkdir -p /config /ranker-media
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
