# Use an official lightweight Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Prevent Python from writing .pyc files to disk and ensure logs print immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV FLASK_APP=src/server/app.py

# Copy just the requirements file first to leverage Docker cache layers
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your backend application code
COPY . .

# Flask defaults to port 5000
EXPOSE 8000

# Run the Flask app and bind it to 0.0.0.0 so Docker can route traffic to it
CMD ["python", "-m", "flask", "run"]