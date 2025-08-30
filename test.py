from django.contrib.auth import get_user_model
U = get_user_model()
try:
    print(U.objects.get(email="lukas.calmbach@bs.ch"))
except Exception as e:
    print(type(e).__name__, str(e))