release: python manage.py migrate --noinput
web: gunicorn report_generator.wsgi --workers 1 --threads 4 --worker-class gthread --max-requests 200 --max-requests-jitter 50 --timeout 60
