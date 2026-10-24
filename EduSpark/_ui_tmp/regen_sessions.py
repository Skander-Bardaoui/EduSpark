import json, os, sys, django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EduSpark.settings")
django.setup()
from django.test import Client
from django.contrib.auth.models import User
ROLES = {"etudiant": "test.ui@example.com", "prof": "prof.test@eduspark.local", "admin": "admin@eduspark.local"}
out = {}
for role, username in ROLES.items():
    u = User.objects.get(username=username)
    c = Client(); c.force_login(u)
    out[role] = {"sessionid": c.cookies["sessionid"].value, "username": username}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("sessions regenerated")
