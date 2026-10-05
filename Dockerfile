FROM python:3.12
# Unbuffered output so container logs appear immediately.
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --upgrade pip
RUN pip install pipenv==2025.0.3

# Install dependencies into the system interpreter: containers don't need a
# virtualenv. --deploy fails the build when Pipfile.lock is stale.
ADD Pipfile Pipfile.lock ./
RUN pipenv install --system --dev --deploy

RUN mkdir app
WORKDIR /app
COPY . /app/

# User uploads (evidence files, team photos); mapped to a docker volume.
RUN mkdir -p media

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
